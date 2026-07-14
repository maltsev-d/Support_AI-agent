# rag/ingestion.py
"""
ЦЕНТРАЛЬНЫЙ МОДУЛЬ pipeline ingestion.

Координирует все шаги: parse → chunk → embed → upsert в PostgreSQL.

UPSERT-ЛОГИКА (ключевая идея):
─────────────────────────────
  Получили файл "cars.txt"
         ↓
  Считаем SHA-256 хеш файла → "abc123"
         ↓
  SELECT id, hash FROM documents WHERE document_id = 'local:products/cars.txt'
         ↓
  ┌── Не найден ──────────────→ INSERT document + INSERT chunks
  │
  ├── Найден, hash = "abc123" → SKIP (файл не изменился, экономим API)
  │
  └── Найден, hash = "aaa111" → DELETE старые chunks
                                 UPDATE document (новый hash)
                                 INSERT новые chunks

ПОЧЕМУ DELETE + INSERT, а не UPDATE chunks:
Количество чанков при изменении файла может измениться. Проще удалить всё
и вставить заново, чем сопоставлять старые и новые чанки по индексу.
ON DELETE CASCADE на kb_chunks не используем здесь явно — мы обновляем
documents запись (не удаляем), поэтому чанки чистим вручную через DELETE.
"""
from __future__ import annotations
import hashlib
import logging
from pathlib import Path

import db
from rag.parsers import parse_file
from rag.chunker import chunk_text
from rag.embedder import embed_documents

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    """
    SHA-256 хеш содержимого файла.
    Читаем блоками по 64KB чтобы не грузить большие файлы целиком в память.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _mime_type(path: Path) -> str:
    mapping = {
        ".txt":  "text/plain",
        ".pdf":  "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    return mapping.get(path.suffix.lower(), "application/octet-stream")


async def ingest_file(
    path: Path,
    category: str,
    source_type: str = "local",
    document_id: str | None = None,
) -> dict:
    """
    Полный цикл ingestion одного файла.

    Параметры:
        path        — путь к файлу на диске
        category    — "company" | "products" (используется при retrieval для фильтрации)
        source_type — "local" | "gdrive" | "notion" (для будущих источников)
        document_id — уникальный ID документа. Если None — генерируем из пути.
                      Для Google Drive сюда придёт file_id от Drive API.

    Возвращает dict с полями:
        status   — "ok" | "updated" | "skipped" | "empty"
        chunks   — количество созданных чанков
    """
    if document_id is None:
        # Формат: "local:products/cars.txt"
        # Для GDrive будет: "gdrive:1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"
        document_id = f"{source_type}:{category}/{path.name}"

    print(f"\n{'='*60}")
    print(f"[ingest] Файл: {path.name}")
    print(f"[ingest] document_id: {document_id}")
    print(f"[ingest] category: {category}")

    # ШАГ 1: Хеш файла
    file_hash = _file_hash(path)
    file_size = path.stat().st_size
    print(f"[ingest] SHA-256: {file_hash[:16]}...  размер: {file_size} байт")

    async with db.pool.acquire() as conn:
        # ШАГ 2: Проверяем существование в БД
        existing = await conn.fetchrow(
            "SELECT id, hash FROM documents WHERE document_id = $1",
            document_id,
        )

        if existing:
            if existing["hash"] == file_hash:
                print(f"[ingest] ✓ Файл не изменился — пропускаем (hash совпадает)")
                return {"status": "skipped", "document_id": document_id, "chunks": 0}
            else:
                print(f"[ingest] ↻ Файл изменился (hash был: {existing['hash'][:16]}...)")
        else:
            print(f"[ingest] + Новый документ, добавляем в БД")

        # ШАГ 3: Парсинг текста
        print(f"\n[parse] Извлекаем текст из {path.suffix.upper()}")
        text = parse_file(path)
        print(f"[parse] Извлечено символов: {len(text)}")
        print(f"[parse] Первые 200 символов: {text[:200]!r}")

        # ШАГ 4: Чанкинг
        print(f"\n[chunk] Режем текст на чанки (CHUNK_SIZE=400 токенов, OVERLAP=80)")
        chunks = chunk_text(text)
        print(f"[chunk] Получено чанков: {len(chunks)}")
        for c in chunks:
            print(f"  Чанк [{c.index}]: {c.token_count} токенов | {c.content[:80]}...")

        if not chunks:
            print(f"[chunk] ⚠ Документ дал 0 чанков — пропускаем")
            return {"status": "empty", "document_id": document_id, "chunks": 0}

        # ШАГ 5: Embeddings
        print(f"\n[embed] Отправляем {len(chunks)} чанков в Cohere API")
        texts = [c.content for c in chunks]
        embeddings = await embed_documents(texts)
        print(f"[embed] Получено векторов: {len(embeddings)}, размерность: {len(embeddings[0])}")
        print(f"[embed] Первые 5 значений вектора чанка [0]: {embeddings[0][:5]}")

        # ШАГ 6: Upsert в БД (в одной транзакции)
        print(f"\n[db] Сохраняем в PostgreSQL (транзакция)")
        async with conn.transaction():
            if existing:
                # Удаляем старые чанки этого документа
                deleted = await conn.execute(
                    "DELETE FROM kb_chunks WHERE document_id = $1",
                    existing["id"],
                )
                print(f"[db] Удалено старых чанков: {deleted}")

                await conn.execute(
                    "UPDATE documents SET hash = $1, file_size = $2, updated_at = now() WHERE id = $3",
                    file_hash, file_size, existing["id"],
                )
                db_doc_id = existing["id"]
                print(f"[db] Документ обновлён (id={db_doc_id})")
            else:
                # Upsert источника: если source уже есть (напр. папка "local:company")
                # просто обновляем updated_at, иначе создаём новый
                source_row = await conn.fetchrow(
                    """INSERT INTO kb_sources (source_type, source_id, category)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (source_type, source_id) DO UPDATE SET updated_at = now()
                       RETURNING id""",
                    source_type,
                    f"{source_type}:{category}",  # source_id — уникальный ключ папки
                    category,
                )
                print(f"[db] kb_sources id={source_row['id']}")

                doc_row = await conn.fetchrow(
                    """INSERT INTO documents
                           (document_id, source_id, filename, category, mime_type, hash, file_size)
                       VALUES ($1, $2, $3, $4, $5, $6, $7)
                       RETURNING id""",
                    document_id, source_row["id"], path.name,
                    category, _mime_type(path), file_hash, file_size,
                )
                db_doc_id = doc_row["id"]
                print(f"[db] Документ создан (id={db_doc_id})")

            # Вставляем чанки батчом
            # $5::vector — приводим list[float] к типу VECTOR(1024) который pgvector понимает
            await conn.executemany(
                """INSERT INTO kb_chunks
                       (document_id, chunk_index, content, token_count, embedding, language)
                   VALUES ($1, $2, $3, $4, $5::vector, $6)""",
                [
                    (db_doc_id, chunk.index, chunk.content,
                     chunk.token_count, "[" + ",".join(map(str, embeddings[i])) + "]", "ru")
                    for i, chunk in enumerate(chunks)
                ],
            )
            print(f"[db] ✓ Вставлено чанков: {len(chunks)}")

    status = "ok" if not existing else "updated"
    print(f"\n[ingest] Готово: {document_id} → {len(chunks)} чанков, status={status}")
    return {"status": status, "document_id": document_id, "chunks": len(chunks)}


async def ingest_directory(directory: Path, category: str) -> list[dict]:
    """
    Загружает все поддерживаемые файлы из папки с одной категорией.
    Запускает ingest_file последовательно — не параллельно,
    чтобы не перегрузить Cohere API одновременными запросами.
    """
    supported = {".txt", ".pdf", ".docx", ".xlsx"}
    results = []

    files = [p for p in sorted(directory.iterdir())
             if p.suffix.lower() in supported and p.is_file()]

    print(f"\n[ingest_dir] Папка: {directory}")
    print(f"[ingest_dir] Категория: {category}")
    print(f"[ingest_dir] Файлов найдено: {len(files)}")

    for path in files:
        result = await ingest_file(path, category)
        results.append(result)

    return results