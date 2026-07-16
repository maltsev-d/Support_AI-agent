# seed_kb.py
"""
Точка входа для первичной загрузки базы знаний.

Запускать из корня проекта:
    python seed_kb.py

Что делает:
1. Инициализирует пул подключений к PostgreSQL
2. Загружает все файлы из knowledge_base/company/ с категорией "company"
3. Загружает все файлы из knowledge_base/products/ с категорией "products"
2. Загружает все файлы из knowledge_base/delivery/ с категорией "delivery"
3. Загружает все файлы из knowledge_base/payments/ с категорией "payments"
4. Выводит итоговую сводку

После первого запуска повторный запуск безопасен:
файлы без изменений будут пропущены (status=skipped).
"""
import asyncio
import logging
from pathlib import Path

# Настраиваем логи ДО импорта модулей — иначе логи из embedder/ingestion
# уйдут в никуда (нет handler'а)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

import db
from rag.ingestion import ingest_directory

# Корень базы знаний — папка рядом со скриптом
KB_ROOT = Path(__file__).parent / "knowledge_base"

# Маппинг папка → category (используется при retrieval для фильтрации)
SOURCES = {
    KB_ROOT / "company": "company",
    KB_ROOT / "products": "products",
    KB_ROOT / "delivery": "delivery",
    KB_ROOT / "payments": "payments",
}


async def main():
    print("=" * 60)
    print("SEED KNOWLEDGE BASE")
    print("=" * 60)

    # Инициализируем пул БД (asyncpg.Pool)
    # Без этого шага все обращения к db.pool упадут с AttributeError
    print("\n[main] Подключаемся к PostgreSQL...")
    await db.init_pool()
    print("[main] Пул подключений создан")

    all_results = []

    for directory, category in SOURCES.items():
        if not directory.exists():
            print(f"\n[main] ⚠ Папка не найдена: {directory} — пропускаем")
            continue

        results = await ingest_directory(directory, category)
        all_results.extend(results)

    # Итоговая сводка
    print("\n" + "=" * 60)
    print("ИТОГ:")
    total_chunks = 0
    for r in all_results:
        status_icon = {"ok": "✓", "updated": "↻", "skipped": "–", "empty": "⚠"}.get(r["status"], "?")
        print(f"  {status_icon} [{r['status']:8s}] {r['document_id']}  ({r['chunks']} чанков)")
        total_chunks += r["chunks"]

    print(f"\nВсего чанков в БД: {total_chunks}")
    print("=" * 60)

    await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())