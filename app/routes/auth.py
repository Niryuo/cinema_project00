from app import db
from app.models import User
from app.forms import LoginForm, RegistrationForm
from flask import flash, redirect, render_template, request, url_for
from flask_login import login_required, login_user, logout_user

from .main import main


@main.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        form = RegistrationForm.from_mapping(request.form)

        if not form.is_valid():
            flash(form.first_error(), "danger")
            return render_template("register.html", username=form.username, email=form.email), 400

        existing_user = User.query.filter((User.username == form.username) | (User.email == form.email)).first()
        if existing_user:
            flash("Пользователь с таким именем или email уже существует", "danger")
            return render_template("register.html", username=form.username, email=form.email), 400

        new_user = User(username=form.username, email=form.email)
        new_user.set_password(form.password)

        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        flash(f"Добро пожаловать, {new_user.username}!", "success")
        return redirect(url_for("main.index"))
    return render_template("register.html")


@main.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        form = LoginForm.from_mapping(request.form)

        if not form.is_valid():
            flash(form.first_error(), "danger")
            return render_template("login.html", username=form.username), 400

        user = User.query.filter_by(username=form.username).first()

        if user and user.check_password(form.password):
            login_user(user)
            flash(f"Добро пожаловать, {user.username}!", "success")
            return redirect(url_for("main.index"))
        flash("Неверный логин или пароль", "danger")

    return render_template("login.html")


@main.route("/logout")
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for("main.index"))