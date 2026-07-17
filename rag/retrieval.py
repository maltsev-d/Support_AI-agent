# rag/retrieval.py
"""
ШАГ 2 в RAG pipeline (после embed_query).

Retrieval — поиск релевантных чанков по векторному запросу.

КАК РАБОТАЕТ ВЕКТОРНЫЙ ПОИСК В PGVECTOR:
pgvector добавляет в PostgreSQL оператор <=> (cosine distance).
Cosine distance измеряет угол между двумя векторами:
  0.0 = одинаковые векторы (идентичный смысл)
  1.0 = перпендикулярные (несвязанные темы)
  2.0 = противоположные (антонимы)

На практике для Cohere embed-multilingual-v3.0:
  < 0.25 — очень похоже
  0.25–0.40 — похоже, релевантно
  0.40–0.55 — слабая связь
  > 0.55 — скорее всего нерелевантно

ПОЧЕМУ ФИЛЬТР ПО CATEGORY:
Без фильтра при вопросе "где ваш офис?" можно получить чанк из products/cars.txt
про московский склад — технически похоже (Москва, адрес), но это не то.
Фильтр `WHERE d.category = $2` гарантирует поиск только в нужном разделе.

ИНДЕКС HNSW:
В БД.sql создан индекс: `USING hnsw (embedding vector_cosine_ops)`
HNSW (Hierarchical Navigable Small World) — приближённый поиск ближайших соседей.
Быстрее точного перебора всех векторов (O(log n) вместо O(n)),
но может пропустить редкие ближайшие векторы. Для нашего масштаба (< 10k чанков)
разница незаметна, зато скорость хорошая.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

import db
from rag.embedder import embed_query

logger = logging.getLogger(__name__)

# Порог отсечения: чанки дальше этого расстояния считаем нерелевантными.
# При distance > THRESHOLD лучше сказать "не знаю", чем давать мусор.
# Значение эмпирическое — уточняется по реальным запросам после деплоя.
SIMILARITY_THRESHOLD = 0.6

TOP_K = 3  # сколько чанков максимум кидаем в промпт LLM


@dataclass
class RetrievedChunk:
    content: str
    distance: float   # cosine distance, чем меньше — тем лучше
    filename: str
    category: str


async def retrieve(
    query: str,
    category: str,
    top_k: int = TOP_K,
    threshold: float = SIMILARITY_THRESHOLD,
) -> list[RetrievedChunk]:
    """
    Ищет top_k наиболее релевантных чанков для запроса в категории.

    ПОРЯДОК ДЕЙСТВИЙ:
    1. Эмбеддим запрос (input_type="search_query" — важно, не "search_document"!)
    2. SQL-запрос с ORDER BY cosine distance + фильтр по category + порог
    3. Возвращаем список RetrievedChunk для передачи в rag_answer

    Если ничего не найдено выше порога — возвращаем пустой список.
    rag_answer знает что делать с пустым списком (не вызывает Groq).
    """
    print(f"\n[retrieve] Запрос: '{query[:80]}'")
    print(f"[retrieve] Категория: {category}, top_k={top_k}, threshold={threshold}")

    # ШАГ 1: Эмбеддим запрос
    print(f"[retrieve] Эмбеддим запрос через Cohere (input_type=search_query)...")
    query_vector = await embed_query(query)
    query_vector = "[" + ",".join(map(str, query_vector)) + "]"
    print(f"[retrieve] Вектор запроса: размерность={len(query_vector)}, первые 3 значения={query_vector[:3]}")
    print(f"[retrieve] Первые 50 символов вектора: {query_vector[:50]}")
    print(f"[retrieve] Последние 20 символов вектора: {query_vector[-20:]}")

    # ШАГ 2: Поиск по pgvector
    # $1::vector — передаём list[float] как VECTOR для оператора <=>
    # <=> — cosine distance (не similarity! distance = 1 - similarity)
    print(f"[retrieve] Ищем в pgvector...")
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.content,
                c.embedding <=> $1::vector AS distance,
                d.filename,
                d.category
            FROM kb_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.category = $2
              AND c.embedding <=> $1::vector < $3
            ORDER BY c.embedding <=> $1::vector
            LIMIT $4
            """,
            query_vector, category, threshold, top_k,
        )

    # ШАГ 3: Форматируем результат
    if not rows:
        print(f"[retrieve] ✗ Ничего не найдено (все чанки дальше порога {threshold})")
        return []

    chunks = [
        RetrievedChunk(
            content=row["content"],
            distance=row["distance"],
            filename=row["filename"],
            category=row["category"],
        )
        for row in rows
    ]

    print(f"[retrieve] Найдено чанков: {len(chunks)}")
    for i, c in enumerate(chunks):
        print(f"  [{i}] distance={c.distance:.4f} | файл={c.filename} | {c.content[:80]}...")

    return chunks


def intent_to_category(intent: str) -> str:
    """
    Маппинг intent классификатора → category в БД.

    Intent — семантика пользователя ("что он имеет в виду").
    Category — технический ключ для фильтрации в pgvector.
    Держим их разделёнными: если переименуем папку, меняем только здесь.
    """
    mapping = {
        "вопрос_по_продукту":   "products",
        "вопрос_по_компании":   "company",
        "вопрос_по_доставке":   "delivery",
        "вопрос_по_оплате":     "payments",
    }
    category = mapping.get(intent, "company")
    print(f"[retrieve] intent '{intent}' → category '{category}'")
    return category