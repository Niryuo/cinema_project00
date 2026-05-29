from datetime import datetime

from app import db
from app.models import Booking, FeedbackRequest, Movie, RefundLog, Screening
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from .main import (
    _active_movie_or_404,
    _active_movie_query,
    _active_screening_or_404,
    _admin_required,
    _release_expired_bookings,
    _save_upload,
    _send_feedback_response_email,
    main,
)


@main.route("/admin")
@login_required
def admin_panel():
    _release_expired_bookings()
    if not _admin_required():
        return "Доступ запрещён", 403
    movies = _active_movie_query().order_by(Movie.created_at.desc()).all()
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

    movie = _active_movie_or_404(id)
    deleted_at = datetime.utcnow()
    movie.is_deleted = True
    movie.deleted_at = deleted_at
    for screening in movie.screenings:
        screening.is_deleted = True
        screening.deleted_at = screening.deleted_at or deleted_at
    db.session.commit()

    flash("Фильм снят с афиши, история покупок и бронирований сохранена", "success")
    return redirect(url_for("main.admin_panel"))


@main.route("/admin/movies/<int:movie_id>/screenings/add", methods=["GET", "POST"])
@login_required
def add_screening(movie_id):
    if not _admin_required():
        return "Доступ запрещён", 403

    movie = _active_movie_or_404(movie_id)

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

    movie = _active_movie_or_404(id)

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

    screenings = (
        Screening.query.filter_by(movie_id=movie.id, is_deleted=False)
        .order_by(Screening.start_time.asc())
        .all()
    )
    return render_template("admin/edit_movie.html", movie=movie, screenings=screenings)


@main.route("/admin/screenings/<int:screening_id>/edit", methods=["GET", "POST"])
@login_required
def edit_screening(screening_id):
    if not _admin_required():
        return "Доступ запрещён", 403

    screening = _active_screening_or_404(screening_id)

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


@main.route("/admin/screenings/<int:screening_id>/delete", methods=["POST"])
@login_required
def delete_screening(screening_id):
    if not _admin_required():
        return "Доступ запрещён", 403

    screening = _active_screening_or_404(screening_id)
    movie_id = screening.movie_id
    screening.is_deleted = True
    screening.deleted_at = datetime.utcnow()
    db.session.commit()

    flash("Сеанс снят с афиши, история бронирований и покупок сохранена", "success")
    return redirect(url_for("main.edit_movie", id=movie_id))


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