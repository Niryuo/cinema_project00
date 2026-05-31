from app import db
from app.models import User
from email_validator import EmailNotValidError, validate_email
from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

from .main import main
import re

PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,}$")


def validate_registration_password(password):
    if not password:
        return "Введите пароль"
    if not PASSWORD_PATTERN.fullmatch(password):
        return (
            "Пароль должен быть не короче 6 символов, содержать только "
            "латинские буквы и цифры, а также минимум одну букву и одну цифру"
        )
    return None


@main.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""
        password_confirm = request.form.get("password_confirm") or ""

        if not username:
            flash("Введите имя пользователя", "danger")
            return render_template("register.html", username=username, email=email), 400

        password_error = validate_registration_password(password)
        if password_error:
            flash(password_error, "danger")
            return render_template("register.html", username=username, email=email), 400

        if password != password_confirm:
            flash("Пароли не совпадают", "danger")
            return render_template("register.html", username=username, email=email), 400

        try:
            valid = validate_email(email)
            email = valid.email
        except EmailNotValidError:
            flash("Некорректный email", "danger")
            return render_template("register.html", username=username, email=email), 400

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


@main.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.index"))