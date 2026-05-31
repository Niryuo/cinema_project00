from dataclasses import dataclass, field
import re
from typing import Mapping

from email_validator import EmailNotValidError, validate_email


PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,}$")
FEEDBACK_TOPICS = {"question", "complaint", "suggestion", "loyalty"}
CONTACT_METHODS = {"email", "phone", "messenger"}


@dataclass
class BaseForm:
    """Small base form with shared error handling."""

    errors: dict[str, str] = field(default_factory=dict, init=False)

    def add_error(self, field_name: str, message: str) -> None:
        self.errors[field_name] = message

    def first_error(self) -> str | None:
        return next(iter(self.errors.values()), None)

    def is_valid(self) -> bool:
        self.errors.clear()
        self.validate()
        return not self.errors

    def validate(self) -> None:
        raise NotImplementedError


@dataclass
class RegistrationForm(BaseForm):
    username: str = ""
    email: str = ""
    password: str = ""
    password_confirm: str = ""

    @classmethod
    def from_mapping(cls, form_data: Mapping[str, str]) -> "RegistrationForm":
        return cls(
            username=(form_data.get("username") or "").strip(),
            email=(form_data.get("email") or "").strip(),
            password=form_data.get("password") or "",
            password_confirm=form_data.get("password_confirm") or "",
        )

    def validate(self) -> None:
        if not self.username:
            self.add_error("username", "Введите имя пользователя")

        if not self.password:
            self.add_error("password", "Введите пароль")
        elif not PASSWORD_PATTERN.fullmatch(self.password):
            self.add_error(
                "password",
                "Пароль должен быть не короче 6 символов, содержать только "
                "латинские буквы и цифры, а также минимум одну букву и одну цифру",
            )

        if self.password != self.password_confirm:
            self.add_error("password_confirm", "Пароли не совпадают")

        try:
            valid = validate_email(self.email, check_deliverability=False)
            self.email = valid.email
        except EmailNotValidError:
            self.add_error("email", "Некорректный email")


@dataclass
class LoginForm(BaseForm):
    username: str = ""
    password: str = ""

    @classmethod
    def from_mapping(cls, form_data: Mapping[str, str]) -> "LoginForm":
        return cls(
            username=(form_data.get("username") or "").strip(),
            password=form_data.get("password") or "",
        )

    def validate(self) -> None:
        if not self.username:
            self.add_error("username", "Введите имя пользователя")
        if not self.password:
            self.add_error("password", "Введите пароль")


@dataclass
class FeedbackForm(BaseForm):
    subject: str = ""
    message: str = ""
    topic: str = "question"
    preferred_contact: str = "email"

    @classmethod
    def from_mapping(cls, form_data: Mapping[str, str]) -> "FeedbackForm":
        return cls(
            subject=(form_data.get("subject") or "").strip(),
            message=(form_data.get("message") or "").strip(),
            topic=form_data.get("topic") or "question",
            preferred_contact=form_data.get("preferred_contact") or "email",
        )

    def validate(self) -> None:
        if not self.subject:
            self.add_error("subject", "Укажите тему обращения")
        if not self.message:
            self.add_error("message", "Укажите текст обращения")
        if self.topic not in FEEDBACK_TOPICS:
            self.topic = "question"
        if self.preferred_contact not in CONTACT_METHODS:
            self.preferred_contact = "email"