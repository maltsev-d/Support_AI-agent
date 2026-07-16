"""
Модели пользовательской части проекта.

Содержит:

- User
- Conversation
- Message

Используется Alembic для создания структуры БД.

Приложение продолжает работать через asyncpg.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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
#from .support import Escalation, Followup

# ==========================================================
# Пользователь Telegram
# ==========================================================

class User(Base):
    """
    Пользователь Telegram.

    Один пользователь может иметь
    множество диалогов.
    """

    __tablename__ = "users"

    # Внутренний ID
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    # Telegram ID
    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
    )

    # Username (@username)
    username: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Дата первого обращения
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Пользователь заблокирован
    is_blocked: Mapped[bool] = mapped_column(
        Boolean,
        server_default="false",
    )

    # Связь:
    # User -> Conversation
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


# ==========================================================
# Диалог
# ==========================================================

class Conversation(Base):
    """
    Один заход пользователя.

    Не вся история общения,
    а одна активная сессия.
    """

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    # Родительский пользователь
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
    )

    # active / resolved / escalated
    status: Mapped[str] = mapped_column(
        Text,
        server_default="active",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # User -> Conversation
    user: Mapped["User"] = relationship(
        back_populates="conversations",
    )

    # Conversation -> Message
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
    )

    escalations: Mapped[list["Escalation"]] = relationship(
        cascade="all, delete-orphan"
    )

    followups: Mapped[list["Followup"]] = relationship(
        cascade="all, delete-orphan"
    )


# ==========================================================
# Сообщение
# ==========================================================

class Message(Base):
    """
    Одно сообщение внутри диалога.

    Может принадлежать:

    user

    assistant

    system
    """

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"),
    )

    role: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    intent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    # Message -> Conversation
    conversation: Mapped["Conversation"] = relationship(
        back_populates="messages",
    )