from datetime import datetime, timedelta
import os
import secrets
import smtplib
import uuid
from email.message import EmailMessage

from app import db
from app.models import Booking, FeedbackRequest, Movie, RefundLog, Screening, User
from email_validator import EmailNotValidError, validate_email
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
            Movie.query.filter(Movie.title.ilike(f"%{search_query}%"))
            .order_by(Movie.created_at.desc())
            .all()
        )
        if movies:
            movie_ids = [movie.id for movie in movies]
            screenings = (
                Screening.query.filter(Screening.movie_id.in_(movie_ids))
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
        movies = Movie.query.order_by(Movie.created_at.desc()).all()

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
    movie = Movie.query.get_or_404(id)
    screenings = Screening.query.filter_by(movie_id=movie.id).order_by(Screening.start_time.asc()).all()

    screenings_data = []
    user_booking_ids = set()
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
    )

@main.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        try:
            valid = validate_email(email)
            email = valid.email
        except EmailNotValidError:
            return "Некорректный email", 400


        existing_user = User.query.filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            return "Пользователь с таким именем или email уже существует", 400

        new_user = User(username=username, email=email)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        flash(f"Добро пожаловать, {new_user.username}!", "success")
        return redirect(url_for("main.index"))
    return render_template("register.html")



@main.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            flash(f"Добро пожаловать, {user.username}!", "success")
            return redirect(url_for("main.index"))
        flash("Неверные данные", "danger")

    return render_template("login.html")


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


@main.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))

@main.route("/admin")
@login_required
def admin_panel():
    _release_expired_bookings()
    if not _admin_required():
        return "Доступ запрещён", 403
    movies = Movie.query.order_by(Movie.created_at.desc()).all()
    latest_bookings = (
        Booking.query.join(Booking.user).join(Screening).join(Movie)
        .order_by(Booking.created_at.desc())
        .limit(30)
        .all()
    )
    active_feedback_requests = (
        FeedbackRequest.query.filter(FeedbackRequest.status != "closed")
        .order_by(FeedbackRequest.created_at.desc())
        .limit(100)
        .all()
    )
    closed_feedback_requests = (
        FeedbackRequest.query.filter_by(status="closed")
        .order_by(FeedbackRequest.responded_at.desc(), FeedbackRequest.created_at.desc())
        .limit(100)
        .all()
    )
    paid_bookings = [b for b in latest_bookings if b.status == "paid"]
    total_revenue = sum((b.price_paid or 0) for b in paid_bookings)
    total_tickets = len(paid_bookings)

    movie_stats = {}
    weekday_stats = {}
    for booking in paid_bookings:
        movie_title = booking.screening.movie.title
        movie_stats[movie_title] = movie_stats.get(movie_title, 0) + 1

        weekday = booking.screening.start_time.strftime("%A")
        weekday_stats[weekday] = weekday_stats.get(weekday, 0) + 1

    popular_movies = sorted(movie_stats.items(), key=lambda x: x[1], reverse=True)[:5]
    popular_weekdays = sorted(weekday_stats.items(), key=lambda x: x[1], reverse=True)

    return render_template(
        "admin/dashboard.html",
        movies=movies,
        latest_bookings=latest_bookings,
        active_feedback_requests=active_feedback_requests,
        closed_feedback_requests=closed_feedback_requests,
        total_revenue=total_revenue,
        total_tickets=total_tickets,
        popular_movies=popular_movies,
        popular_weekdays=popular_weekdays,
    )

@main.route("/admin/bookings/history")
@login_required
def admin_bookings_history():
    if not _admin_required():
        return "Доступ запрещён", 403

    all_bookings = (
        Booking.query.join(Booking.user).join(Screening).join(Movie)
        .order_by(Booking.created_at.desc())
        .all()
    )
    return render_template("admin/bookings_history.html", bookings=all_bookings)

@main.route("/add_movie", methods=["GET", "POST"])
@login_required
def add_movie():
    if not _admin_required():
        return "Доступ запрещён", 403

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        duration = int(request.form.get("duration"))
        genre = request.form.get("genre")
        director = request.form.get("director")
        actors = request.form.get("actors")
        country = request.form.get("country")
        production_year = int(request.form.get("production_year"))
        age_rating = request.form.get("age_rating")
        poster_path = _save_upload(request.files.get("poster"))


        movie = Movie(
            title=title,
            description=description,
            duration=duration,
            genre=genre,
            director=director,
            actors=actors,
            country=country,
            production_year=production_year,
            age_rating=age_rating,
            poster_path=poster_path,
        )

        db.session.add(movie)
        db.session.commit()

        flash("Фильм добавлен", "success")
        return redirect(url_for("main.admin_panel"))

    return render_template("add_movie.html")

@main.route("/delete_movie/<int:id>")
@login_required
def delete_movie(id):
    if not _admin_required():
        return "Доступ запрещён", 403

    movie = Movie.query.get_or_404(id)
    db.session.delete(movie)
    db.session.commit()

    flash("Фильм удален", "success")
    return redirect(url_for("main.admin_panel"))


@main.route("/admin/movies/<int:movie_id>/screenings/add", methods=["GET", "POST"])
@login_required
def add_screening(movie_id):
    if not _admin_required():
        return "Доступ запрещён", 403

    movie = Movie.query.get_or_404(movie_id)

    if request.method == "POST":
        try:
            hall_name = request.form.get("hall_name")
            start_time_raw = request.form.get("start_time")
            hall_rows = int(request.form.get("hall_rows"))
            hall_cols = int(request.form.get("hall_cols"))

            ticket_price = float(request.form.get("ticket_price"))
            start_time = datetime.strptime(start_time_raw, "%Y-%m-%dT%H:%M")

            screening = Screening(
                movie_id=movie.id,
                hall_name=hall_name,
                start_time=start_time,
                hall_rows=hall_rows,
                hall_cols=hall_cols,
                ticket_price=ticket_price,
            )

            db.session.add(screening)
            db.session.commit()

            flash("Сеанс добавлен", "success")
            return redirect(url_for("main.movie_detail", id=movie.id))

        except Exception:
            flash("Ошибка при добавлении сеанса", "danger")
            return redirect(url_for("main.add_screening", movie_id=movie.id))

    return render_template("add_screening.html", movie=movie)


@main.route("/edit_movie/<int:id>", methods=["GET", "POST"])
@login_required
def edit_movie(id):
    if not _admin_required():
        return "Доступ запрещён", 403

    movie = Movie.query.get_or_404(id)

    if request.method == "POST":
        movie.title = request.form.get("title")
        movie.description = request.form.get("description")
        movie.duration = int(request.form.get("duration"))
        movie.genre = request.form.get("genre")
        movie.director = request.form.get("director")
        movie.actors = request.form.get("actors")
        movie.country = request.form.get("country")
        movie.production_year = int(request.form.get("production_year"))
        movie.age_rating = request.form.get("age_rating")

        new_poster = _save_upload(request.files.get("poster"))
        if new_poster:
            movie.poster_path = new_poster

        db.session.commit()
        flash("Фильм обновлен", "success")
        return redirect(url_for("main.edit_movie", id=movie.id))

    screenings = Screening.query.filter_by(movie_id=movie.id).order_by(Screening.start_time.asc()).all()
    return render_template("admin/edit_movie.html", movie=movie, screenings=screenings)

@main.route("/admin/screenings/<int:screening_id>/edit", methods=["GET", "POST"])
@login_required
def edit_screening(screening_id):
    if not _admin_required():
        return "Доступ запрещён", 403

    screening = Screening.query.get_or_404(screening_id)

    if request.method == "POST":
        hall_name = request.form.get("hall_name")
        start_time_raw = request.form.get("start_time")
        hall_rows = int(request.form.get("hall_rows"))
        hall_cols = int(request.form.get("hall_cols"))
        ticket_price = float(request.form.get("ticket_price"))

        if hall_rows < 1 or hall_cols < 1:
            flash("Размер зала должен быть больше нуля", "danger")
            return redirect(url_for("main.edit_screening", screening_id=screening.id))

        screening.hall_name = hall_name
        screening.start_time = datetime.strptime(start_time_raw, "%Y-%m-%dT%H:%M")
        screening.hall_rows = hall_rows
        screening.hall_cols = hall_cols
        screening.ticket_price = ticket_price

        poster_override = _save_upload(request.files.get("screening_poster"))
        if poster_override:
            screening.poster_override_path = poster_override

        db.session.commit()
        flash("Параметры зала и сеанса обновлены", "success")
        return redirect(url_for("main.movie_detail", id=screening.movie_id))

    return render_template("admin/edit_screening.html", movie=screening.movie, screening=screening)


@main.route("/screenings/<int:screening_id>/book", methods=["POST"])
@login_required
def book_seat(screening_id):
    screening = Screening.query.get_or_404(screening_id)
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


@main.route("/admin/bookings/<int:booking_id>/issue-receipt", methods=["POST"])
@login_required
def issue_receipt(booking_id):
    if not _admin_required():
        return "Доступ запрещён", 403

    booking = Booking.query.get_or_404(booking_id)
    if booking.status != "paid":
        flash("Чек можно выдать только для оплаченного билета", "danger")
        return redirect(url_for("main.admin_panel"))

    booking.receipt_issued_at = datetime.utcnow()
    booking.receipt_issued_by_id = current_user.id
    db.session.commit()

    flash(f"Чек по билету {booking.ticket_code} выдан", "success")
    return redirect(url_for("main.admin_panel"))

@main.route("/feedback", methods=["POST"])
@login_required
def send_feedback():
    if current_user.role == "admin":
        flash("Администратор не может отправлять обратную связь самому себе.", "danger")
        return redirect(url_for("main.profile"))
    subject = request.form.get("subject", "").strip()
    message = request.form.get("message", "").strip()
    topic = request.form.get("topic", "question")
    preferred_contact = request.form.get("preferred_contact", "email")

    if not subject or not message:
        flash("Укажите тему и текст обращения", "danger")
        return redirect(url_for("main.profile"))
    if topic not in {"question", "complaint", "suggestion", "loyalty"}:
        topic = "question"
    if preferred_contact not in {"email", "phone", "messenger"}:
        preferred_contact = "email"

    feedback = FeedbackRequest(
        user_id=current_user.id,
        topic=topic,
        preferred_contact=preferred_contact,
        subject=subject,
        message=message,
        status="sent",
    )
    db.session.add(feedback)
    db.session.commit()
    flash("Спасибо за обратную связь! Мы получили обращение и скоро ответим удобным способом.", "success")
    return redirect(url_for("main.profile"))


@main.route("/admin/feedback/<int:feedback_id>/reply", methods=["POST"])
@login_required
def admin_reply_feedback(feedback_id):
    if not _admin_required():
        return "Доступ запрещён", 403

    feedback = FeedbackRequest.query.get_or_404(feedback_id)
    admin_comment = request.form.get("admin_comment", "").strip()

    if not admin_comment:
        flash("Введите ответ клиенту", "danger")
        return redirect(url_for("main.admin_panel"))

    feedback.admin_comment = admin_comment
    feedback.status = "closed"
    feedback.responded_at = datetime.utcnow()

    try:
        _send_feedback_response_email(feedback)
        feedback.response_emailed_at = datetime.utcnow()
        flash("Ответ отправлен клиенту на email, заявка закрыта.", "success")
    except Exception:
        flash("Заявка закрыта, но письмо клиенту пока не отправилось.", "warning")

    db.session.commit()
    return redirect(url_for("main.admin_panel"))

@main.route("/admin/bookings/<int:booking_id>/refund", methods=["POST"])
@login_required
def admin_refund_booking(booking_id):
    if not _admin_required():
        return "Доступ запрещён", 403

    booking = Booking.query.get_or_404(booking_id)
    if booking.status != "paid":
        flash("Возврат доступен только для оплаченных билетов", "danger")
        return redirect(url_for("main.admin_panel"))

    reason = request.form.get("reason", "").strip() or "Возврат по запросу"

    refund = RefundLog(
        booking_id=booking.id,
        admin_id=current_user.id,
        amount=booking.price_paid or 0,
        reason=reason,
    )

    booking.status = "refunded"
    booking.canceled_at = datetime.utcnow()
    booking.cancel_reason = f"Возврат админом: {reason}"
    booking.ticket_code = None

    db.session.add(refund)
    db.session.commit()
    flash("Возврат выполнен. Место снова доступно для бронирования.", "success")
    return redirect(url_for("main.admin_panel"))

@main.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)

    if booking.user_id != current_user.id:
        return "Доступ запрещён", 403

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

