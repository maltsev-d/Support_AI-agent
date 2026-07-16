"""
Базовый класс всех моделей SQLAlchemy.

Зачем он нужен?

SQLAlchemy хранит описание всех таблиц проекта
в объекте Base.metadata.

Alembic использует именно Base.metadata,
чтобы сравнить модели Python с текущей базой данных
и автоматически создать миграции.

Само приложение (FastAPI + asyncpg) эти модели
использовать не обязано.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """
    Базовый класс для всех ORM-моделей.
    """

    pass