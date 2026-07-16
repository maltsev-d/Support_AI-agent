"""
Модели поддержки пользователей.

Содержит:

- Escalation
- Followup

Используются Alembic для создания структуры БД.

Приложение продолжает работать через asyncpg.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Text,
    func,
)

from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from .base import Base
#from .users import Conversation


# ==========================================================
# Эскалация оператору
# ==========================================================

class Escalation(Base):
    """
    Инцидент, переданный оператору.

    Создается, если:

    • пользователь недоволен
    • низкая уверенность классификатора
    • ручная эскалация
    """

    __tablename__ = "escalations"

    # Внутренний ID
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    # Родительский диалог
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey(
            "conversations.id",
            ondelete="CASCADE",
        ),
    )

    # Причина эскалации
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Краткое резюме,
    # которое будет отправлено оператору
    summary: Mapped[str | None] = mapped_column(
        Text,
    )

    # pending
    # active
    # handled
    status: Mapped[str] = mapped_column(
        Text,
        server_default="pending",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    handled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )

    # Связь с диалогом
    conversation: Mapped["Conversation"] = relationship(
        back_populates="escalations"
    )


# ==========================================================
# Follow-up задачи
# ==========================================================

class Followup(Base):
    """
    Отложенная задача.

    Используется n8n
    для повторного контакта
    с пользователем.
    """

    __tablename__ = "followups"

    # Внутренний ID
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    # Родительский диалог
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey(
            "conversations.id",
            ondelete="CASCADE",
        ),
    )

    # Когда необходимо выполнить задачу
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    # scheduled
    # sent
    # cancelled
    status: Mapped[str] = mapped_column(
        Text,
        server_default="scheduled",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Связь с диалогом
    conversation: Mapped["Conversation"] = relationship(
        back_populates="followups"
    )