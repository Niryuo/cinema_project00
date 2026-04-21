import os

class Config:
    SECRET_KEY = "supersecretkey"
    SQLALCHEMY_DATABASE_URI = "postgresql://postgres:1234@localhost/cinema_db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False