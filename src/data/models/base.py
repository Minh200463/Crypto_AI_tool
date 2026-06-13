"""
SQLAlchemy Base — shared by all models.
Import this in every model file.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
