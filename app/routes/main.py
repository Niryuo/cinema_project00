from datetime import datetime, timedelta
import os
import secrets
import smtplib
import uuid
from email.message import EmailMessage

from app import db
from app.forms import FeedbackForm
from app.models import Booking, FavoriteScreening, FeedbackRequest, Movie, RefundLog, Screening, User
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = "app/static/uploads"

main = Blueprint("main", __name__)


def _release_expired_bookings(notify_user_id=None):
    now = datetime.utcnow()
    expired = (
        Booking.query.filter(
            Booking.status == "reserved",
            Booking.expires_at.isnot(None),
            Booking.expires_at < now,
        )
        .all()
    )

    expired_count = 0
    for booking in expired:
        booking.status = "cancelled"
        booking.canceled_at = now
        booking.cancel_reason = "Автоотмена: время подтверждения (15 минут) истекло"
        expired_count += 1

    if expired_count:
        db.session.commit()

    if notify_user_id:
        my_expired = [b for b in expired if b.user_id == notify_user_id]
        if my_expired:
            flash(f"{len(my_expired)} бронь(ей) автоматически отменены: 15 минут на подтверждение истекли.", "danger")
def _admin_required():
    if current_user.role != "admin":
        return False
    return True


def _ensure_loyalty_card(user):
    if user.loyalty_card_number:
        return

    while True:
        candidate = f"CP-{secrets.randbelow(10 ** 10):010d}"
        exists = User.query.filter_by(loyalty_card_number=candidate).first()
        if not exists:
            user.loyalty_card_number = candidate
            break

def _active_movie_query():
    return Movie.query.filter(Movie.is_deleted.is_(False))


def _active_screening_query():
    return Screening.query.join(Screening.movie).filter(
        Screening.is_deleted.is_(False),
        Movie.is_deleted.is_(False),
    )


def _booking_screening_removed(booking):
    return bool(booking.screening.is_deleted or booking.screening.movie.is_deleted)


def _active_movie_or_404(movie_id):
    return _active_movie_query().filter(Movie.id == movie_id).first_or_404()


def _active_screening_or_404(screening_id):
    return _active_screening_query().filter(Screening.id == screening_id).first_or_404()


def _loyalty_payment_quote(user, ticket_price, payment_mode="save"):
    user.update_loyalty_status()
    status_meta = user.status_meta()
    discount_amount = round(ticket_price * status_meta["discount"] / 100, 2)
    discounted_price = max(ticket_price - discount_amount, 0)
    points_to_use = 0
    if payment_mode == "use" and user.loyalty_points > 0:
        points_to_use = min(user.loyalty_points, int(discounted_price))

    final_price = round(discounted_price - points_to_use, 2)
    earned_points = int(final_price * status_meta["cashback"] / 100)

    return {
        "status_meta": status_meta,
        "discount_amount": discount_amount,
        "discounted_price": discounted_price,
        "points_to_use": points_to_use,
        "final_price": final_price,
        "earned_points": earned_points,
    }


def _favorite_status(favorite):
    now = datetime.utcnow()
    paid_booking = (
        Booking.query.filter_by(
            user_id=favorite.user_id,
            screening_id=favorite.screening_id,
            status="paid",
        )
        .order_by(Booking.paid_at.desc(), Booking.created_at.desc())
        .first()
    )

    if favorite.screening.is_deleted or favorite.screening.movie.is_deleted:
        return {
            "code": "deleted",
            "label": "Завершенный сеанс",
            "badge": "text-bg-dark",
            "icon": "fa-box-archive",
            "booking": paid_booking,
        }
    if paid_booking:
        if favorite.screening.start_time and favorite.screening.start_time > now:
            return {
                "code": "planned",
                "label": "Планируемые",
                "badge": "text-bg-primary",
                "icon": "fa-calendar-check",
                "booking": paid_booking,
            }
        return {
            "code": "watched",
            "label": "Просмотрено",
            "badge": "text-bg-success",
            "icon": "fa-circle-check",
            "booking": paid_booking,
        }

    has_upcoming_screenings = Screening.query.filter(
        Screening.movie_id == favorite.screening.movie_id,
        Screening.is_deleted.is_(False),
        Screening.start_time >= now,
    ).first()
    if not has_upcoming_screenings:
        return {
            "code": "no_screenings",
            "label": "Сеансов больше нет",
            "badge": "text-bg-warning",
            "icon": "fa-calendar-xmark",
            "booking": None,
        }

    return {
        "code": "empty",
        "label": "В избранном",
        "badge": "text-bg-secondary",
        "icon": "fa-heart",
        "booking": None,
    }
def _generate_ticket_code():
    while True:
        code = f"CP-TKT-{secrets.token_hex(4).upper()}"
        if not Booking.query.filter_by(ticket_code=code).first():
            return code


def _save_upload(file_storage):
    if not file_storage or file_storage.filename == "":
        return None

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filename = f"{uuid.uuid4()}_{secure_filename(file_storage.filename)}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file_storage.save(filepath)
    return f"uploads/{filename}"

def _ticket_qr_url(booking):
    payload = f"ticket:{booking.ticket_code or booking.id}:user:{booking.user_id}:screening:{booking.screening_id}:seat:{booking.seat_row}-{booking.seat_col}"
    return f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={payload}"
def _send_email(to_email, subject, body):
    sender = os.getenv("MAIL_SENDER", "no-reply@cinema-project.local")
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "25"))

    if smtp_host:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        msg.set_content(body)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
            smtp.send_message(msg)

    return True


def _send_ticket_email(booking):

    subject = f"Ваш билет #{booking.ticket_code}"
    body = (
        f"Здравствуйте, {booking.user.username}!\n\n"
        f"Ваш билет готов.\n"
        f"Фильм: {booking.screening.movie.title}\n"
        f"Сеанс: {booking.screening.start_time.strftime('%d.%m.%Y %H:%M')}\n"
        f"Зал: {booking.screening.hall_name}\n"
        f"Место: ряд {booking.seat_row}, место {booking.seat_col}\n"
        f"Стоимость: {booking.price_paid:.2f} ₽\n"
        f"Код билета: {booking.ticket_code}\n"
    )
    return _send_email(booking.user.email, subject, body)

def _send_feedback_response_email(feedback):
        subject = f"Ответ на обращение: {feedback.subject}"
        body = (
            f"Здравствуйте, {feedback.user.username}!\n\n"
            f"Мы ответили на ваше обращение от "
            f"{feedback.created_at.strftime('%d.%m.%Y %H:%M') if feedback.created_at else '—'}.\n\n"
            f"Тема: {feedback.subject}\n\n"
            f"Ваше сообщение:\n{feedback.message}\n\n"
            f"Ответ администратора:\n{feedback.admin_comment}\n\n"
            f"Статус обращения: {feedback.status_label()}.\n"
        )
        return _send_email(feedback.user.email, subject, body)

@main.route("/")
def index():
    _release_expired_bookings(notify_user_id=current_user.id if current_user.is_authenticated else None)
    search_query = request.args.get("q", "").strip()
    search_message = None
    screenings_by_movie = {}

    if search_query:
        movies = (
            _active_movie_query()
            .filter(Movie.title.ilike(f"%{search_query}%"))
            .order_by(Movie.created_at.desc())
            .all()
        )
        if movies:
            movie_ids = [movie.id for movie in movies]
            screenings = (
                Screening.query.filter(
                    Screening.movie_id.in_(movie_ids),
                    Screening.is_deleted.is_(False),
                )
                .order_by(Screening.start_time.asc())
                .all()
            )
            for screening in screenings:
                screenings_by_movie.setdefault(screening.movie_id, []).append(screening)

            if not screenings:
                search_message = f"Фильм «{search_query}» найден, но сеансов для него пока нет."
        else:
            search_message = f"Фильм или сеанс по запросу «{search_query}» не найден."
    else:
        movies = _active_movie_query().order_by(Movie.created_at.desc()).all()

    return render_template(
        "index.html",
        movies=movies,
        search_query=search_query,
        search_message=search_message,
        screenings_by_movie=screenings_by_movie,
    )



@main.route("/movies/<int:id>")
def movie_detail(id):
    _release_expired_bookings(notify_user_id=current_user.id if current_user.is_authenticated else None)
    movie = _active_movie_or_404(id)
    screenings = (
        Screening.query.filter_by(movie_id=movie.id, is_deleted=False)
        .order_by(Screening.start_time.asc())
        .all()
    )

    screenings_data = []
    user_booking_ids = set()
    favorite_screening_ids = set()
    if current_user.is_authenticated:
        _ensure_loyalty_card(current_user)
        current_user.update_loyalty_status()
        db.session.commit()
        user_booking_ids = {
            booking.id
            for booking in Booking.query.filter(
                Booking.user_id == current_user.id,
                Booking.status.in_(["reserved", "confirmed", "paid"]),
            ).all()}
        favorite_screening_ids = {
            favorite.screening_id
            for favorite in FavoriteScreening.query.filter_by(user_id=current_user.id).all()
        }

    for screening in screenings:
        active_bookings = Booking.query.filter(
            Booking.screening_id == screening.id,
            Booking.status.in_(["reserved", "confirmed", "paid"]),
        ).all()
        occupied = {(booking.seat_row, booking.seat_col): booking for booking in active_bookings}
        screenings_data.append({"screening": screening, "occupied": occupied})

    my_bookings = []
    if current_user.is_authenticated:
        my_bookings = (
            Booking.query.join(Screening)
            .filter(
                Booking.user_id == current_user.id,
                Booking.status.in_(["reserved", "confirmed", "paid"]),
                Screening.movie_id == movie.id,
                Screening.is_deleted.is_(False),
            )
            .order_by(Screening.start_time.asc())
            .all()
        )

    return render_template(
        "movie_detail.html",
        movie=movie,
        screenings_data=screenings_data,
        my_bookings=my_bookings,
        user_booking_ids=user_booking_ids,
        favorite_screening_ids=favorite_screening_ids,
    )

@main.route("/dashboard")
@login_required
def dashboard():
    return redirect(url_for("main.profile"))
@main.route("/profile")
@login_required
def profile():
    _release_expired_bookings(notify_user_id=current_user.id)
    _ensure_loyalty_card(current_user)
    current_user.update_loyalty_status()
    db.session.commit()

    bookings = (
        Booking.query.join(Screening).join(Movie)
        .filter(Booking.user_id == current_user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )

    paid_bookings = [b for b in bookings if b.status == "paid"]
    latest_paid_bookings = paid_bookings[:5]
    latest_bookings = bookings[:5]
    latest_feedback_requests = (
        FeedbackRequest.query.filter_by(user_id=current_user.id)
        .order_by(FeedbackRequest.created_at.desc())
        .limit(3)
        .all()
    )
    status_meta = current_user.status_meta()
    paid_bookings_total = len(paid_bookings)
    if status_meta["next_tickets"]:
        status_progress = int(
            min(
                100,
                max(
                    0,
                    (paid_bookings_total - status_meta["min_tickets"])
                    / (status_meta["next_tickets"] - status_meta["min_tickets"])
                    * 100,
                ),
            )
        )
        tickets_to_next_status = max(status_meta["next_tickets"] - paid_bookings_total, 0)
    else:
        status_progress = 100
        tickets_to_next_status = 0

    return render_template(
        "profile.html",
        bookings=latest_bookings,
        paid_bookings=latest_paid_bookings,
        feedback_requests=latest_feedback_requests,
        paid_bookings_total=paid_bookings_total,
        bookings_total=len(bookings),
        status_meta=status_meta,
        status_progress=status_progress,
        tickets_to_next_status=tickets_to_next_status,
        ticket_qr_url=_ticket_qr_url,
    )


@main.route("/favorites")
@login_required
def favorites():
    _release_expired_bookings(notify_user_id=current_user.id)
    favorite_items = (
        FavoriteScreening.query.join(FavoriteScreening.screening).join(Screening.movie)
        .filter(FavoriteScreening.user_id == current_user.id)
        .order_by(FavoriteScreening.created_at.desc())
        .all()
    )
    statuses = {favorite.id: _favorite_status(favorite) for favorite in favorite_items}

    return render_template(
        "favorites.html",
        favorite_items=favorite_items,
        statuses=statuses,
    )


@main.route("/screenings/<int:screening_id>/favorite", methods=["POST"])
@login_required
def add_favorite(screening_id):
    if current_user.role == "admin":
        flash("Избранное доступно клиентам.", "danger")
        return redirect(request.referrer or url_for("main.index"))

    screening = _active_screening_or_404(screening_id)
    favorite = FavoriteScreening.query.filter_by(
        user_id=current_user.id,
        screening_id=screening.id,
    ).first()

    if favorite:
        flash("Этот сеанс уже есть в избранном.", "success")
    else:
        db.session.add(FavoriteScreening(user_id=current_user.id, screening_id=screening.id))
        db.session.commit()
        flash("Сеанс добавлен в избранное.", "success")

    return redirect(request.referrer or url_for("main.movie_detail", id=screening.movie_id))


@main.route("/favorites/<int:favorite_id>/remove", methods=["POST"])
@login_required
def remove_favorite(favorite_id):
    favorite = FavoriteScreening.query.get_or_404(favorite_id)
    if favorite.user_id != current_user.id:
        return "Доступ запрещён", 403

    movie_id = favorite.screening.movie_id
    movie_removed = favorite.screening.movie.is_deleted
    db.session.delete(favorite)
    db.session.commit()
    flash("Сеанс удалён из избранного.", "success")

    fallback = url_for("main.index") if movie_removed else url_for("main.movie_detail", id=movie_id)
    return redirect(request.referrer or fallback)
@main.route("/profile/history")
@login_required
def profile_history():
    _release_expired_bookings(notify_user_id=current_user.id)
    bookings = (
        Booking.query.join(Screening).join(Movie)
        .filter(Booking.user_id == current_user.id)
        .order_by(Booking.created_at.desc())
        .all()
    )
    paid_bookings = [b for b in bookings if b.status == "paid"]

    return render_template(
        "profile_history.html",
        bookings=bookings,
        paid_bookings=paid_bookings,
        ticket_qr_url=_ticket_qr_url,
    )


@main.route("/screenings/<int:screening_id>/book", methods=["POST"])
@login_required
def book_seat(screening_id):
    screening = _active_screening_or_404(screening_id)
    seat_row = int(request.form.get("seat_row"))
    seat_col = int(request.form.get("seat_col"))

    if seat_row < 1 or seat_row > screening.hall_rows or seat_col < 1 or seat_col > screening.hall_cols:
        flash("Некорректное место", "danger")
        return redirect(url_for("main.movie_detail", id=screening.movie_id))

    seat_is_taken = Booking.query.filter(
        Booking.screening_id == screening.id,
        Booking.seat_row == seat_row,
        Booking.seat_col == seat_col,
        Booking.status.in_(["reserved", "confirmed", "paid"]),
    ).first()
    if seat_is_taken:
        flash("Это место уже занято", "danger")
        return redirect(url_for("main.movie_detail", id=screening.movie_id))

    my_bookings_count = Booking.query.filter(
        Booking.screening_id == screening.id,
        Booking.user_id == current_user.id,
        Booking.status.in_(["reserved", "confirmed", "paid"]),
    ).count()
    if my_bookings_count >= 5:
        flash("Нельзя забронировать больше 5 мест на один сеанс", "danger")
        return redirect(url_for("main.movie_detail", id=screening.movie_id))

    booking = Booking(
        screening_id=screening.id,
        user_id=current_user.id,
        seat_row=seat_row,
        seat_col=seat_col,
        status="reserved",
        expires_at=datetime.utcnow() + timedelta(minutes=15),
    )

    db.session.add(booking)
    db.session.commit()

    flash(f"Место Ряд {seat_row}, Место {seat_col} забронировано. На подтверждение есть 15 минут ", "success")
    return redirect(url_for("main.movie_detail", id=screening.movie_id))

@main.route("/bookings/<int:booking_id>/confirm", methods=["POST"])
@login_required
def confirm_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        return "Доступ запрещён", 403

    if _booking_screening_removed(booking):
        flash("Сеанс снят с афиши. Бронирование сохранено в истории как завершенное.", "warning")
        return redirect(url_for("main.profile_history"))

    if booking.status == "reserved" and booking.expires_at and booking.expires_at < datetime.utcnow():
        booking.status = "cancelled"
        booking.canceled_at = datetime.utcnow()
        booking.cancel_reason = "Автоотмена: время подтверждения (15 минут) истекло"
        db.session.commit()
        flash("Бронирование автоматически отменено: время подтверждения истекло.", "danger")
        return redirect(url_for("main.movie_detail", id=booking.screening.movie_id))

    if booking.status != "reserved":
        flash("Подтверждение доступно только для новых броней", "danger")
        return redirect(url_for("main.movie_detail", id=booking.screening.movie_id))

    booking.status = "confirmed"
    booking.confirmed_at = datetime.utcnow()
    booking.expires_at = None
    db.session.commit()

    flash("Бронирование подтверждено. Можно оплачивать билет.", "success")
    return redirect(url_for("main.movie_detail", id=booking.screening.movie_id))


@main.route("/bookings/<int:booking_id>/pay", methods=["POST"])
@login_required
def pay_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    if booking.user_id != current_user.id:
        return "Доступ запрещён", 403

    if _booking_screening_removed(booking):
        flash("Сеанс снят с афиши. Оплата недоступна, история бронирования сохранена.", "warning")
        return redirect(url_for("main.profile_history"))

    if booking.status != "confirmed":
        flash("Сначала подтвердите бронирование", "danger")
        return redirect(url_for("main.movie_detail", id=booking.screening.movie_id))

    payment_mode = request.form.get("payment_mode", "save")
    simulated_result = request.form.get("simulate_payment", "ok")

    if simulated_result == "fail":
        flash("Оплата не прошла: недостаточно средств на карте. Бронь сохранена в статусе 'Подтверждено'.", "danger")
        return redirect(url_for("main.movie_detail", id=booking.screening.movie_id))

    ticket_price = booking.screening.ticket_price
    _ensure_loyalty_card(current_user)
    payment_quote = _loyalty_payment_quote(current_user, ticket_price, payment_mode)

    booking.status = "paid"
    booking.paid_at = datetime.utcnow()
    booking.price_paid = payment_quote["final_price"]
    booking.ticket_code = _generate_ticket_code()

    if payment_quote["points_to_use"]:
        current_user.loyalty_points -= payment_quote["points_to_use"]
    current_user.loyalty_points += payment_quote["earned_points"]
    current_user.cashback_balance += payment_quote["earned_points"]
    db.session.flush()
    current_user.update_loyalty_status()

    try:
        _send_ticket_email(booking)
        booking.emailed_at = datetime.utcnow()
        flash(
            f"Оплата прошла успешно: списано {payment_quote['points_to_use']} баллов, "
            f"начислено {payment_quote['earned_points']} баллов. Билет отправлен на email и сохранен в личном кабинете.",
            "success",
        )
    except Exception:
        flash(
            f"Оплата прошла успешно: списано {payment_quote['points_to_use']} баллов, "
            f"начислено {payment_quote['earned_points']} баллов. Билет сохранен в личном кабинете (email пока не отправлен).",
            "success",
        )
    db.session.commit()
    return redirect(url_for("main.profile"))


@main.route("/feedback", methods=["POST"])
@login_required
def send_feedback():

    form = FeedbackForm.from_mapping(request.form)

    if not form.is_valid():
        flash(form.first_error(), "danger")
        return redirect(url_for("main.profile"))

    if current_user.role == "admin":
        flash("Администратор не может отправлять обратную связь самому себе.", "danger")
        return redirect(url_for("main.profile"))

    feedback = FeedbackRequest(
        user_id=current_user.id,
        topic=form.topic,
        preferred_contact=form.preferred_contact,
        subject=form.subject,
        message=form.message,
        status="sent",
    )

    db.session.add(feedback)
    db.session.commit()

    flash(
        "Спасибо за обратную связь! Мы получили обращение и скоро ответим удобным способом.",
        "success",
    )

    return redirect(url_for("main.profile"))
@main.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)

    if booking.user_id != current_user.id:
        return "Доступ запрещён", 403

    if _booking_screening_removed(booking):
        flash("Сеанс снят с афиши. Запись сохранена в истории как завершенная.", "warning")
        return redirect(url_for("main.profile_history"))

    if booking.status  == "cancelled":
        flash("Бронирование уже отменено", "danger")
        return redirect(url_for("main.movie_detail", id=booking.screening.movie_id))

    cancel_reason = request.form.get("cancel_reason", "").strip()
    if not cancel_reason:
        flash("Укажите причину отмены", "danger")
        return redirect(url_for("main.movie_detail", id=booking.screening.movie_id))

    booking.status = "cancelled"
    booking.cancel_reason = cancel_reason
    booking.canceled_at = datetime.utcnow()
    current_user.update_loyalty_status()
    db.session.commit()

    flash("Бронирование отменено", "success")
    return redirect(url_for("main.movie_detail", id=booking.screening.movie_id))

from app.routes import auth, admin  # noqa: E402,F401