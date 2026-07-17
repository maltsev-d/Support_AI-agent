# rag/drive_ingestion.py
"""
Связующий слой между Drive API и существующим ingestion pipeline.

Скачивает файл из Drive во временный файл на диске →
передаёт в ingest_file (который уже умеет parse/chunk/embed/upsert).

ПОЧЕМУ ВРЕМЕННЫЙ ФАЙЛ:
ingest_file принимает Path, парсеры тоже работают с Path.
Переписывать их под bytes — лишняя работа. Проще скачать во temp,
обработать, удалить. tempfile.NamedTemporaryFile гарантирует очистку.
"""
from __future__ import annotations
import logging
import tempfile
from pathlib import Path

import db
from config import DRIVE_FOLDER_CATEGORY
from rag.drive_client import download_file, list_files
from rag.ingestion import ingest_file

logger = logging.getLogger(__name__)


async def ingest_drive_file(
    file_id: str,
    filename: str,
    mime_type: str,
    category: str,
    web_view_link: str | None = None,
) -> dict:
    """
    Скачивает файл с Drive и прогоняет через ingestion pipeline.
    document_id формируется как "gdrive:{file_id}" — стабильный,
    не меняется при переименовании файла на Drive.
    """
    document_id = f"gdrive:{file_id}"
    logger.info(f"[drive_ingest] {filename} ({document_id})")

    content, extension = await download_file(file_id, mime_type)

    # Пишем во временный файл с правильным расширением —
    # парсеры определяют формат по path.suffix
    with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        result = await ingest_file(
            path=tmp_path,
            category=category,
            source_type="gdrive",
            document_id=document_id,
        )
        # Сохраняем web_view_link если есть
        if web_view_link:
            await _update_external_url(document_id, web_view_link)
        return result
    finally:
        tmp_path.unlink(missing_ok=True)


async def delete_drive_file(file_id: str) -> bool:
    """
    Удаляет документ и все его чанки из БД по file_id.
    Возвращает True если что-то было удалено.
    """
    document_id = f"gdrive:{file_id}"
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM documents WHERE document_id = $1",
            document_id,
        )
        if not row:
            logger.info(f"[drive_ingest] {document_id} не найден в БД, пропускаем")
            return False

        # kb_chunks удалятся каскадно (ON DELETE CASCADE на document_id FK)
        await conn.execute(
            "DELETE FROM documents WHERE id = $1",
            row["id"],
        )
        logger.info(f"[drive_ingest] Удалён документ {document_id}")
        return True


async def sync_folder(folder_id: str, category: str) -> list[dict]:
    """
    Полная синхронизация папки — используется при первом запуске
    или ручном ресинке. Проходит по всем файлам в папке,
    ingest_file сам пропустит неизменённые (hash совпадает).
    """
    files = await list_files(folder_id)
    logger.info(f"[drive_ingest] sync_folder {category}: {len(files)} файлов")

    results = []
    for f in files:
        result = await ingest_drive_file(
            file_id=f["id"],
            filename=f["name"],
            mime_type=f["mimeType"],
            category=category,
            web_view_link=f.get("webViewLink"),
        )
        results.append(result)
    return results


async def _update_external_url(document_id: str, url: str) -> None:
    async with db.pool.acquire() as conn:
        await conn.execute(
            "UPDATE documents SET external_url = $1 WHERE document_id = $2",
            url, document_id,
        )