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


def _send_ticket_email(booking):
    sender = os.getenv("MAIL_SENDER", "no-reply@cinema-project.local")
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "25"))

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

    if smtp_host:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = booking.user.email
        msg.set_content(body)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
            smtp.send_message(msg)

    return True


@main.route("/")
def index():
    _release_expired_bookings(notify_user_id=current_user.id if current_user.is_authenticated else None)
    movies = Movie.query.order_by(Movie.created_at.desc()).all()
    return render_template("index.html", movies=movies)



@main.route("/movies/<int:id>")
def movie_detail(id):
    _release_expired_bookings(notify_user_id=current_user.id if current_user.is_authenticated else None)
    movie = Movie.query.get_or_404(id)
    screenings = Screening.query.filter_by(movie_id=movie.id).order_by(Screening.start_time.asc()).all()

    screenings_data = []
    user_booking_ids = set()
    if current_user.is_authenticated:
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

    movie_history = (
        Movie.query.join(Screening).join(Booking)
        .filter(Booking.user_id == current_user.id)
        .distinct()
        .order_by(Movie.title.asc())
        .all()
    )
    paid_bookings = [b for b in bookings if b.status == "paid"]

    return render_template(
        "profile.html",
        bookings=bookings,
        paid_bookings=paid_bookings,
        movie_history=movie_history,
        status_meta=current_user.status_meta(),
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
        .limit(200)
        .all()
    )
    feedback_requests = FeedbackRequest.query.order_by(FeedbackRequest.created_at.desc()).limit(200).all()
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

    return render_template("admin/dashboard.html", movies=movies, latest_bookings=latest_bookings, feedback_requests=feedback_requests, total_revenue=total_revenue, total_tickets=total_tickets, popular_movies=popular_movies, popular_weekdays=popular_weekdays)


@main.route("/add_movie", methods=["GET", "POST"])
@login_required
def add_movie():
    if not _admin_required():
        return "Доступ запрещён", 403

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        duration = int(request.form.get("duration"))
        poster_path = _save_upload(request.files.get("poster"))


        movie = Movie(
            title=title,
            description=description,
            duration=duration,
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
    points_to_use = 0
    if payment_mode == "use" and current_user.loyalty_points > 0:
        points_to_use = min(current_user.loyalty_points, int(ticket_price))

    booking.status = "paid"
    booking.paid_at = datetime.utcnow()
    booking.price_paid = ticket_price - points_to_use
    booking.ticket_code = _generate_ticket_code()

    _ensure_loyalty_card(current_user)
    if points_to_use:
        current_user.loyalty_points -= points_to_use
    else:
        current_user.loyalty_points += int(booking.price_paid)
    current_user.cashback_balance += booking.price_paid * 0.05
    current_user.update_loyalty_status()

    try:
        _send_ticket_email(booking)
        booking.emailed_at = datetime.utcnow()
        flash("Оплата прошла успешно. Билет отправлен на email и сохранен в личном кабинете.", "success")
    except Exception:
        flash("Оплата прошла успешно. Билет сохранен в личном кабинете (email пока не отправлен).", "success")

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
    subject = request.form.get("subject", "").strip()
    message = request.form.get("message", "").strip()
    topic = request.form.get("topic", "question")
    preferred_contact = request.form.get("preferred_contact", "email")

    if not subject or not message:
        flash("Укажите тему и текст обращения", "danger")
        return redirect(url_for("main.profile"))

    feedback = FeedbackRequest(
        user_id=current_user.id,
        topic=topic,
        preferred_contact=preferred_contact,
        subject=subject,
        message=message,
    )
    db.session.add(feedback)
    db.session.commit()
    flash("Заявка отправлена администратору", "success")
    return redirect(url_for("main.profile"))


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

