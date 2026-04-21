from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)

    password_hash = db.Column(db.String(255), nullable=False)

    role = db.Column(db.String(20), default="user")  # user / admin

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    bookings = db.relationship("Booking", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Movie(db.Model):
    __tablename__ = "movies"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    screenings = db.relationship("Screening", back_populates="movie", cascade="all, delete-orphan")


class Screening(db.Model):
    __tablename__ = "screenings"

    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey("movies.id"), nullable=False)
    hall_name = db.Column(db.String)
    start_time = db.Column(db.DateTime)
    hall_rows = db.Column(db.Integer, nullable=False, default=5)
    hall_cols = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    movie = db.relationship("Movie", back_populates="screenings")
    bookings = db.relationship("Booking", back_populates="screening", cascade="all, delete-orphan")


class Booking(db.Model):
    __tablename__ = "bookings"

    id = db.Column(db.Integer, primary_key=True)
    screening_id = db.Column(db.Integer, db.ForeignKey("screenings.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    seat_row = db.Column(db.Integer, nullable=False)
    seat_col = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="active")
    cancel_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    canceled_at = db.Column(db.DateTime)

    screening = db.relationship("Screening", back_populates="bookings")
    user = db.relationship("User", back_populates="bookings")

