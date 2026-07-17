"""
RAG-модели.

Содержит:

- KBSource
- Document
- KBChunk

Используются Alembic для миграций.

Приложение продолжает работать через asyncpg.
"""

from __future__ import annotations
from datetime import datetime
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    CheckConstraint,
    func,
    Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)
from .base import Base


# ==========================================================
# Источник базы знаний
# ==========================================================

class KBSource(Base):
    """
    Источник документов.

    Примеры:

    google_drive

    website

    manual_upload

    Один источник может содержать множество документов.
    """

    __tablename__ = "kb_sources"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    source_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    source_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    documents: Mapped[list["Document"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            name="uq_kb_source",
        ),
    )


# ==========================================================
# Документ
# ==========================================================

class Document(Base):
    """
    Исходный документ.

    Именно из него позже создаются чанки.
    """

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    document_id: Mapped[str] = mapped_column(
        Text,
        unique=True,
        nullable=False,
    )

    source_id: Mapped[int] = mapped_column(
        ForeignKey(
            "kb_sources.id",
            ondelete="CASCADE",
        ),
    )

    filename: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    external_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    mime_type: Mapped[str | None] = mapped_column(
        Text,
    )

    hash: Mapped[str | None] = mapped_column(
        Text,
    )

    file_size: Mapped[int | None] = mapped_column(
        BigInteger,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    source: Mapped["KBSource"] = relationship(
        back_populates="documents",
    )

    chunks: Mapped[list["KBChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("document_id", name="documents_document_id_key"),
        Index("idx_documents_document_id", "document_id"),
        Index("idx_documents_category", "category"),
    )


# ==========================================================
# Chunk
# ==========================================================

class KBChunk(Base):
    """
    Один кусок текста документа.

    Именно эта таблица участвует
    в vector search.
    """

    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )

    document_id: Mapped[int] = mapped_column(
        ForeignKey(
            "documents.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    token_count: Mapped[int | None] = mapped_column(
        Integer,
    )

    language: Mapped[str] = mapped_column(
        Text,
        server_default="ru",
    )

    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1024),
    )

    chunk_metadata: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    document: Mapped["Document"] = relationship(
        back_populates="chunks",
    )

    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_chunk_index_positive"),
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk"),
        Index("idx_chunks_document_id", "document_id"),
        Index(
            "idx_kb_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

# ==========================================================
# DriveWatchChannel
# ==========================================================

class DriveWatchChannel(Base):
    __tablename__ = "drive_watch_channels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    folder_id: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    channel_id: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("folder_id", name="uq_drive_watch_folder_id"),
    )