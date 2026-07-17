# seed_drive.py
"""
Первичная синхронизация базы знаний из Google Drive.

Запускать из корня проекта:
    python seed_drive.py

Что делает:
1. Инициализирует пул БД
2. Для каждой папки-категории вызывает sync_folder
3. Выводит итоговую сводку

Повторный запуск безопасен — файлы без изменений пропускаются (hash совпадает).
"""
import asyncio
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

import db
from config import DRIVE_FOLDER_MAP
from rag.drive_ingestion import sync_folder


async def main():
    print("=" * 60)
    print("SEED KNOWLEDGE BASE FROM GOOGLE DRIVE")
    print("=" * 60)

    await db.init_pool()
    print("[main] Пул подключений создан\n")

    all_results = []

    for category, folder_id in DRIVE_FOLDER_MAP.items():
        print(f"\n[main] Синхронизирую категорию: {category} (folder_id={folder_id})")
        results = await sync_folder(folder_id, category)
        all_results.extend(results)

    print("\n" + "=" * 60)
    print("ИТОГ:")
    total_chunks = 0
    for r in all_results:
        status_icon = {"ok": "✓", "updated": "↻", "skipped": "–", "empty": "⚠"}.get(r["status"], "?")
        print(f"  {status_icon} [{r['status']:8s}] {r['document_id']}  ({r['chunks']} чанков)")
        total_chunks += r["chunks"]

    print(f"\nВсего чанков загружено: {total_chunks}")
    print("=" * 60)

    await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())