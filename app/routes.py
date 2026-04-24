from datetime import datetime
import secrets
from app import db
from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from app.models import Booking, Movie, Screening, User
import os
import uuid
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = "app/static/uploads"


main = Blueprint("main", __name__)


@main.route("/")
def index():
    movies = Movie.query.order_by(Movie.created_at.desc()).all()
    return render_template("index.html", movies=movies)



@main.route("/movies/<int:id>")
def movie_detail(id):
    movie = Movie.query.get_or_404(id)
    screenings = Screening.query.filter_by(movie_id=movie.id).order_by(Screening.start_time.asc()).all()

    screenings_data = []
    user_booking_ids = set()
    if current_user.is_authenticated:
        user_booking_ids = {
            booking.id
            for booking in Booking.query.filter_by(user_id=current_user.id, status="active").all()
        }

    for screening in screenings:
        active_bookings = Booking.query.filter_by(screening_id=screening.id, status="active").all()
        occupied = {(booking.seat_row, booking.seat_col): booking for booking in active_bookings}
        screenings_data.append({"screening": screening, "occupied": occupied})

    my_bookings = []
    if current_user.is_authenticated:
        my_bookings = (
            Booking.query.join(Screening)
            .filter(
                Booking.user_id == current_user.id,
                Booking.status == "active",
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
    # flash(f"Добро пожаловать, {current_user.username}!", "success")
    # return redirect(url_for("main.index"))
    return redirect(url_for("main.profile"))


def _ensure_loyalty_card(user):
    if user.loyalty_card_number:
        return

    while True:
        candidate = f"CP-{secrets.randbelow(10 ** 10):010d}"
        exists = User.query.filter_by(loyalty_card_number=candidate).first()
        if not exists:
            user.loyalty_card_number = candidate
            break


@main.route("/profile")
@login_required
def profile():
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

    return render_template(
        "profile.html",
        bookings=bookings,
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
    if current_user.role != "admin":
        return "Доступ запрещён", 403
    movies = Movie.query.order_by(Movie.created_at.desc()).all()
    return render_template("admin/dashboard.html", movies=movies)



@main.route("/add_movie", methods=["GET", "POST"])
@login_required
def add_movie():
    if current_user.role != "admin":
        return "Доступ запрещён", 403

    if request.method == "POST":
        title = request.form.get("title")
        description = request.form.get("description")
        duration = request.form.get("duration")

        file = request.files.get("poster")  # ВОТ ЭТА СТРОКА

        poster_path = None

        if file and file.filename != "":
            import os
            import uuid
            from werkzeug.utils import secure_filename

            filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
            filepath = os.path.join("app/static/uploads", filename)

            file.save(filepath)

            poster_path = f"uploads/{filename}"

        movie = Movie(
            title=title,
            description=description,
            duration=int(duration),
            poster_path=poster_path
        )

        db.session.add(movie)
        db.session.commit()

        flash("Фильм добавлен", "success")
        return redirect(url_for("main.admin_panel"))

    return render_template("add_movie.html")

@main.route("/delete_movie/<int:id>")
@login_required
def delete_movie(id):
    if current_user.role != "admin":
        return "Доступ запрещён", 403

    movie = Movie.query.get_or_404(id)
    db.session.delete(movie)
    db.session.commit()

    flash("Фильм удален", "success")
    return redirect(url_for("main.admin_panel"))


    screenings = Screening.query.filter_by(movie_id=movie.id).order_by(Screening.start_time.asc()).all()
    return render_template("admin/edit_movie.html", movie=movie, screenings=screenings)


@main.route("/admin/movies/<int:movie_id>/screenings/add", methods=["GET", "POST"])
@login_required
def add_screening(movie_id):
    if current_user.role != "admin":
        return "Доступ запрещён", 403

    movie = Movie.query.get_or_404(movie_id)

    if request.method == "POST":
        try:
            hall_name = request.form.get("hall_name")
            start_time_raw = request.form.get("start_time")
            hall_rows = int(request.form.get("hall_rows"))
            hall_cols = int(request.form.get("hall_cols"))

            start_time = datetime.strptime(start_time_raw, "%Y-%m-%dT%H:%M")

            screening = Screening(
                movie_id=movie.id,
                hall_name=hall_name,
                start_time=start_time,
                hall_rows=hall_rows,
                hall_cols=hall_cols,
            )

            db.session.add(screening)
            db.session.commit()

            flash("Сеанс добавлен", "success")
            return redirect(url_for("main.movie_detail", id=movie.id))

        except Exception as e:
            print("ERROR:", e)
            flash("Ошибка при добавлении сеанса", "danger")
            return redirect(url_for("main.add_screening", movie_id=movie.id))

    return render_template("add_screening.html", movie=movie)


@main.route("/edit_movie/<int:id>", methods=["GET", "POST"])
@login_required
def edit_movie(id):
    if current_user.role != "admin":
        return "Доступ запрещён", 403

    movie = Movie.query.get_or_404(id)

    if request.method == "POST":
        movie.title = request.form.get("title")
        movie.description = request.form.get("description")
        movie.duration = int(request.form.get("duration"))

        db.session.commit()
        return redirect(url_for("main.admin_dashboard"))
    return render_template("admin/edit_screening.html", movie=movie, screening=None)

@main.route("/admin/screenings/<int:screening_id>/edit", methods=["GET", "POST"])
@login_required
def edit_screening(screening_id):
    if current_user.role != "admin":
        return "Доступ запрещён", 403

    screening = Screening.query.get_or_404(screening_id)

    if request.method == "POST":
        hall_name = request.form.get("hall_name")
        start_time_raw = request.form.get("start_time")
        hall_rows = int(request.form.get("hall_rows"))
        hall_cols = int(request.form.get("hall_cols"))

        if hall_rows < 1 or hall_cols < 1:
            flash("Размер зала должен быть больше нуля", "danger")
            return redirect(url_for("main.edit_screening", screening_id=screening.id))

        screening.hall_name = hall_name
        screening.start_time = datetime.strptime(start_time_raw, "%Y-%m-%dT%H:%M")
        screening.hall_rows = hall_rows
        screening.hall_cols = hall_cols

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

    seat_is_taken = Booking.query.filter_by(
        screening_id=screening.id,
        seat_row=seat_row,
        seat_col=seat_col,
        status="active",
    ).first()
    if seat_is_taken:
        flash("Это место уже занято", "danger")
        return redirect(url_for("main.movie_detail", id=screening.movie_id))

    my_bookings_count = Booking.query.filter_by(
        screening_id=screening.id,
        user_id=current_user.id,
        status="active",
    ).count()
    if my_bookings_count >= 5:
        flash("Нельзя забронировать больше 5 мест на один сеанс", "danger")
        return redirect(url_for("main.movie_detail", id=screening.movie_id))

    booking = Booking(
        screening_id=screening.id,
        user_id=current_user.id,
        seat_row=seat_row,
        seat_col=seat_col,
    )
    _ensure_loyalty_card(current_user)
    current_user.loyalty_points += 100
    current_user.cashback_balance += 20.0

    db.session.add(booking)
    current_user.update_loyalty_status()
    db.session.commit()

    flash(f"Место Ряд {seat_row}, Место {seat_col} успешно забронировано", "success")
    return redirect(url_for("main.movie_detail", id=screening.movie_id))


@main.route("/bookings/<int:booking_id>/cancel", methods=["POST"])
@login_required
def cancel_booking(booking_id):
    booking = Booking.query.get_or_404(booking_id)

    if booking.user_id != current_user.id:
        return "Доступ запрещён", 403

    if booking.status != "active":
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

