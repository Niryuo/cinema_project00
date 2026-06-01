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
    role = db.Column(db.String(20), default="user")  # user/ admin
    loyalty_card_number = db.Column(db.String(32), unique=True)
    loyalty_points = db.Column(db.Integer, nullable=False, default=0)
    cashback_balance = db.Column(db.Float, nullable=False, default=0.0)
    loyalty_status = db.Column(db.String(20), nullable=False, default="guest")
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    bookings = db.relationship("Booking", back_populates="user", foreign_keys="Booking.user_id", cascade="all, delete-orphan")
    favorite_screenings = db.relationship("FavoriteScreening", back_populates="user", cascade="all, delete-orphan")
    feedback_requests = db.relationship("FeedbackRequest", back_populates="user", cascade="all, delete-orphan")
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def total_active_bookings(self):
        if self.id:
            return Booking.query.filter_by(user_id=self.id, status="paid").count()
        return sum(1 for booking in self.bookings if booking.status == "paid")

    def update_loyalty_status(self):
        if self.role == "admin":
            self.loyalty_status = "admin"
            return

        paid_tickets = self.total_active_bookings()
        if paid_tickets >= 20:
            self.loyalty_status = "legend"
        elif paid_tickets >= 10:
            self.loyalty_status = "fan"
        elif paid_tickets >= 5:
            self.loyalty_status = "newbie"
        else:
            self.loyalty_status = "guest"

    def status_meta(self):
        mapping = {
            "admin": {
                "label": "Админ",
                "discount": 0,
                "cashback": 0,
                "icon": "fa-user-shield",
                "min_tickets": 0,
                "next_label": None,
                "next_tickets": None,
                "gradient": "linear-gradient(135deg, #5f0f40 0%, #310e68 100%)",
            },
            "guest": {
                "label": "Гость",
                "discount": 0,
                "cashback": 5,
                "icon": "fa-ticket",
                "min_tickets": 0,
                "next_label": "Новичок",
                "next_tickets": 5,
                "gradient": "linear-gradient(135deg, #3a3a3a 0%, #151515 100%)",
            },
            "newbie": {
                "label": "Новичок",
                "discount": 3,
                "cashback": 7,
                "icon": "fa-star",
                "min_tickets": 5,
                "next_label": "Любитель кино",
                "next_tickets": 10,
                "gradient": "linear-gradient(135deg, #243b55 0%, #141e30 100%)",
            },
            "fan": {
                "label": "Любитель кино",
                "discount": 5,
                "cashback": 10,
                "icon": "fa-clapperboard",
                "min_tickets": 10,
                "next_label": "Кино-легенда",
                "next_tickets": 20,
                "gradient": "linear-gradient(135deg, #8e2de2 0%, #4a00e0 100%)",
            },
            "legend": {
                "label": "Кино-легенда",
                "discount": 10,
                "cashback": 15,
                "icon": "fa-crown",
                "min_tickets": 20,
                "next_label": None,
                "next_tickets": None,
                "gradient": "linear-gradient(135deg, #f7971e 0%, #ffd200 100%)",
            },
        }
        if self.role == "admin":
            return mapping["admin"]
        return mapping.get(self.loyalty_status, mapping["guest"])


class Movie(db.Model):
    __tablename__ = "movies"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.Integer)
    poster_path = db.Column(db.String(255))
    genre = db.Column(db.String(120))
    director = db.Column(db.String(150))
    actors = db.Column(db.Text)
    age_rating = db.Column(db.String(20))
    country = db.Column(db.String(120))
    production_year = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    deleted_at = db.Column(db.DateTime)
    screenings = db.relationship("Screening", back_populates="movie", cascade="all, delete-orphan")


class Screening(db.Model):
    __tablename__ = "screenings"
    id = db.Column(db.Integer, primary_key=True)
    movie_id = db.Column(db.Integer, db.ForeignKey("movies.id"), nullable=False)
    hall_name = db.Column(db.String)
    start_time = db.Column(db.DateTime)
    hall_rows = db.Column(db.Integer, nullable=False, default=5)
    hall_cols = db.Column(db.Integer, nullable=False, default=10)
    ticket_price = db.Column(db.Float, nullable=False, default=450.0)
    poster_override_path = db.Column(db.String(255))
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    deleted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    movie = db.relationship("Movie", back_populates="screenings")
    bookings = db.relationship("Booking", back_populates="screening", cascade="all, delete-orphan")
    favorites = db.relationship("FavoriteScreening", back_populates="screening", cascade="all, delete-orphan")


class FavoriteScreening(db.Model):
    __tablename__ = "favorite_screenings"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    screening_id = db.Column(db.Integer, db.ForeignKey("screenings.id"), nullable=False)
    note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", back_populates="favorite_screenings")
    screening = db.relationship("Screening", back_populates="favorites")

    __table_args__ = (
        db.UniqueConstraint("user_id", "screening_id", name="uq_favorite_screenings_user_screening"),
    )

class Booking(db.Model):
    __tablename__ = "bookings"
    id = db.Column(db.Integer, primary_key=True)

    screening_id = db.Column(
        db.Integer,
        db.ForeignKey("screenings.id"),
        nullable=False
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    seat_row = db.Column(db.Integer, nullable=False)
    seat_col = db.Column(db.Integer, nullable=False)

    status = db.Column(db.String(20), nullable=False, default="reserved")
    ticket_code = db.Column(db.String(32), unique=True)
    price_paid = db.Column(db.Float)

    confirmed_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)
    emailed_at = db.Column(db.DateTime)

    receipt_issued_at = db.Column(db.DateTime)
    receipt_issued_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    refunded_at = db.Column(db.DateTime)
    refund_amount = db.Column(db.Float)
    refund_reason = db.Column(db.Text)
    cancel_reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    expires_at = db.Column(db.DateTime)
    canceled_at = db.Column(db.DateTime)

    user = db.relationship("User", back_populates="bookings", foreign_keys=[user_id])
    receipt_issued_by = db.relationship("User", foreign_keys=[receipt_issued_by_id])

    screening = db.relationship(
        "Screening",
        back_populates="bookings"
    )

class FeedbackRequest(db.Model):
    __tablename__ = "feedback_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    topic = db.Column(db.String(30), nullable=False, default="question")
    preferred_contact = db.Column(db.String(20), nullable=False, default="email")
    subject = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="sent")
    admin_comment = db.Column(db.Text)
    responded_at = db.Column(db.DateTime)
    response_emailed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    user = db.relationship("User", back_populates="feedback_requests")

    def status_label(self):
        labels = {
            "new": "Отправлено",
            "sent": "Отправлено",
            "in_progress": "В работе",
            "closed": "Закрыто",
        }
        return labels.get(self.status, self.status)

    def status_badge_class(self):
        classes = {
            "new": "text-bg-info",
            "sent": "text-bg-info",
            "in_progress": "text-bg-warning",
            "closed": "text-bg-success",
        }
        return classes.get(self.status, "text-bg-secondary")

    def is_closed(self):
        return self.status == "closed"
class RefundLog(db.Model):
    __tablename__ = "refund_logs"

    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("bookings.id"), nullable=False)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    booking = db.relationship("Booking")
    admin = db.relationship("User")
