# rag/embedder.py
"""
ШАГ 5 в pipeline ingestion / ШАГ 1 в retrieval.

Embedder — обёртка над Cohere API для получения векторных представлений текста.

ЧТО ТАКОЕ EMBEDDING:
Функция, превращающая текст в вектор из 1024 чисел. Похожие по смыслу
тексты дают близкие векторы. Именно это позволяет искать "сломался станок"
и находить чанк с текстом "оборудование не включается".

ПОЧЕМУ ДВА input_type:
embed-multilingual-v3.0 оптимизирует вектор по-разному в зависимости от роли:
- "search_document" → вектор "для хранения", оптимизирован для того чтобы
  его находили при поиске
- "search_query" → вектор "для запроса", оптимизирован для поиска по хранилищу

Если оба раза передать "search_document" — cosine similarity упадёт на ~10-15%.
Это не баг, это feature: модель обучена на парах (query, document).

ПОЧЕМУ БАТЧИ ПО 96:
Cohere принимает максимум 96 текстов за один HTTP-запрос.
Файл с 200 чанками → 3 запроса, не 200. Экономит время и rate limit.

ПОЧЕМУ asyncio.to_thread:
Cohere Python SDK синхронный (блокирующий). Если вызвать его напрямую
в async-функции FastAPI — заблокируем весь event loop на время HTTP-запроса.
to_thread запускает синхронный вызов в отдельном потоке, event loop свободен.
"""
from __future__ import annotations
import asyncio
import logging
import cohere
from config import settings

logger = logging.getLogger(__name__)

# Синхронный клиент. Async-клиент в cohere SDK помечен как beta.
_co = cohere.Client(api_key=settings.cohere_api_key)

EMBED_MODEL = "embed-multilingual-v3.0" # embed-v4.0
BATCH_SIZE = 96


async def embed_documents(texts: list[str]) -> list[list[float]]:
    """
    Эмбеддит тексты для индексации (сохранения в БД).
    input_type="search_document" — обязательно при ingestion.
    """
    logger.info(f"[embedder] embed_documents: {len(texts)} текстов")
    result = await _embed_batched(texts, input_type="search_document")
    logger.info(f"[embedder] Получено {len(result)} векторов, размерность {len(result[0])}")
    return result


async def embed_query(text: str) -> list[float]:
    """
    Эмбеддит запрос пользователя для поиска.
    input_type="search_query" — обязательно при retrieval.
    """
    logger.info(f"[embedder] embed_query: '{text[:60]}'")
    results = await _embed_batched([text], input_type="search_query")
    return results[0]


async def _embed_batched(texts: list[str], input_type: str) -> list[list[float]]:
    """
    Режет тексты на батчи по BATCH_SIZE, запускает последовательно.
    Последовательно, не параллельно — чтобы не упереться в rate limit Cohere.
    """
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(texts) - 1) // BATCH_SIZE + 1
        logger.info(
            f"[embedder] Батч {batch_num}/{total_batches} "
            f"({len(batch)} текстов, input_type={input_type})"
        )
        embeddings = await asyncio.to_thread(_embed_sync, batch, input_type)
        all_embeddings.extend(embeddings)

    return all_embeddings


def _embed_sync(texts: list[str], input_type: str) -> list[list[float]]:
    """
    Синхронный вызов Cohere API. Запускается в отдельном потоке через to_thread.

    embedding_types=["float"] — просим float32 векторы.
    Cohere также поддерживает "int8", "uint8", "binary" — компактнее, но менее точные.
    """
    response = _co.embed(
        texts=texts,
        model=EMBED_MODEL,
        input_type=input_type,
        embedding_types=["float"],
    )
    result = response.embeddings.float_
    #print(f"DEBUG _embed_sync: type={type(result)}, len={len(result)}, type[0]={type(result[0])}, len[0]={len(result[0])}")
    return result