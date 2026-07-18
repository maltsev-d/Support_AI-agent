# rag/drive_client.py
"""
Клиент Google Drive API для ingestion базы знаний.

Авторизация через Service Account — никаких токенов, никакого OAuth.
Библиотека сама обновляет access_token каждый час.

Все методы Drive API синхронные — оборачиваем в asyncio.to_thread
чтобы не блокировать event loop FastAPI.
"""
from __future__ import annotations
import asyncio
import io
import json
import logging
import tempfile
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# MIME-типы Google Docs → формат экспорта → расширение файла
GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
}

# MIME-типы нативных файлов которые умеем парсить
SUPPORTED_MIME_TYPES = {
    "text/plain",
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _build_service():
    """Создаёт синхронный Drive API клиент."""
    creds_dict = json.loads(settings.google_credentials)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


# Синглтон — создаём один раз при импорте
_service = _build_service()


async def list_files(folder_id: str) -> list[dict]:
    """
    Возвращает список файлов в папке.
    Только поддерживаемые форматы — нативные + Google Docs/Sheets.
    Папки и остальное игнорируем.
    """
    def _list():
        all_mime = (
            SUPPORTED_MIME_TYPES
            | set(GOOGLE_EXPORT_MAP.keys())
        )
        mime_filter = " or ".join(
            f"mimeType='{m}'" for m in all_mime
        )
        query = f"'{folder_id}' in parents and ({mime_filter}) and trashed=false"

        result = _service.files().list(
            q=query,
            fields="files(id, name, mimeType, modifiedTime, webViewLink, md5Checksum)",
            pageSize=100,
        ).execute()
        return result.get("files", [])

    return await asyncio.to_thread(_list)


async def download_file(file_id: str, mime_type: str) -> tuple[bytes, str]:
    """
    Скачивает файл и возвращает (bytes, расширение).

    Нативные файлы — скачиваем как есть.
    Google Docs/Sheets — экспортируем в docx/xlsx.
    """
    def _download():
        if mime_type in GOOGLE_EXPORT_MAP:
            export_mime, extension = GOOGLE_EXPORT_MAP[mime_type]
            request = _service.files().export_media(
                fileId=file_id,
                mimeType=export_mime,
            )
        else:
            extension = _mime_to_extension(mime_type)
            request = _service.files().get_media(fileId=file_id)

        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        return buffer.getvalue(), extension

    return await asyncio.to_thread(_download)


async def get_start_page_token() -> str:
    """Получает начальный pageToken для changes.list."""
    def _get():
        return _service.changes().getStartPageToken().execute()["startPageToken"]
    return await asyncio.to_thread(_get)
    return str(result)  # ← добавить str()


async def list_changes(page_token: str) -> tuple[list[dict], str]:
    if isinstance(page_token, bytes):
        page_token = page_token.decode()
    ...
    """
    Возвращает (список изменений, новый pageToken).
    Изменения — все файлы на Drive после page_token.
    Фильтрацию по папке делаем сами через parents.
    """
    def _list():
        result = _service.changes().list(
            pageToken=page_token,
            fields="nextPageToken,newStartPageToken,changes(fileId,removed,file(id,name,mimeType,parents,trashed,webViewLink,md5Checksum))",
            includeRemoved=True,
        ).execute()
        changes = result.get("changes", [])
        new_token = result.get("newStartPageToken") or result.get("nextPageToken", page_token)
        return changes, new_token

    return await asyncio.to_thread(_list)

"""
async def watch_folder(folder_id: str, webhook_url: str, channel_id: str) -> dict:
    
    # Подписывается на изменения папки.
    # channel_id — уникальный ID подписки (uuid), нужен для обновления.
    # Возвращает dict с expiration (unix ms) и resourceId для отписки.
    
    def _watch():
        body = {
            "id": channel_id,
            "type": "web_hook",
            "address": webhook_url,
        }
        return _service.files().watch(
            fileId=folder_id,
            body=body,
        ).execute()

    return await asyncio.to_thread(_watch)
"""
async def watch_changes(webhook_url: str, channel_id: str, page_token: str) -> dict:
    """
    Подписка на все изменения Drive.
    Одна подписка вместо per-папочных — ловит изменения файлов внутри папок.
    """
    def _watch():
        body = {
            "id": channel_id,
            "type": "web_hook",
            "address": webhook_url,
        }
        return _service.changes().watch(
            pageToken=page_token,
            body=body,
        ).execute()

    return await asyncio.to_thread(_watch)

async def stop_watch(channel_id: str, resource_id: str) -> None:
    """Отменяет подписку Watch."""
    def _stop():
        _service.channels().stop(body={
            "id": channel_id,
            "resourceId": resource_id,
        }).execute()

    await asyncio.to_thread(_stop)


def _mime_to_extension(mime_type: str) -> str:
    mapping = {
        "text/plain": ".txt",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    }
    return mapping.get(mime_type, ".bin")