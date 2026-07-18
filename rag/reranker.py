# rag/reranker.py
"""
Второй проход RAG pipeline — пересортировка кандидатов от pgvector.

ЗАЧЕМ:
pgvector ранжирует по cosine distance между векторами — это грубая метрика.
Reranker получает пару (запрос, чанк) и оценивает релевантность напрямую,
понимая семантику запроса относительно каждого конкретного чанка.

FLOW:
retrieve() → top-10 кандидатов по cosine distance
rerank()   → пересортировка, отсечение слабых → top-3
rag_answer() → Groq получает уже качественный список

ПОЧЕМУ rerank-multilingual-v3.0:
Та же Cohere, уже есть API-ключ. Поддерживает русский.
Синхронный клиент — оборачиваем в asyncio.to_thread (как embedder).

RELEVANCE_THRESHOLD:
Cohere возвращает score от 0 до 1. Шкала нелинейная:
  > 0.5  — явно релевантно
  0.1–0.5 — частично релевантно
  < 0.1  — скорее всего мусор
Ставим 0.1 как минимальный фильтр — убирает совсем нерелевантные чанки,
которые прошли cosine threshold, но не несут нужного смысла.
После наполнения базы знаний можно поднять до 0.2–0.3.
"""
from __future__ import annotations
import asyncio
import logging

import cohere

from config import settings
from rag.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

_co = cohere.Client(api_key=settings.cohere_api_key)

RERANK_MODEL = "rerank-multilingual-v3.0"
RERANK_TOP_N = 3
RELEVANCE_THRESHOLD = 0.1


async def rerank(
    query: str,
    chunks: list[RetrievedChunk],
    top_n: int = RERANK_TOP_N,
    threshold: float = RELEVANCE_THRESHOLD,
) -> list[RetrievedChunk]:
    """
    Пересортировывает chunks по релевантности к query.

    Если chunks пустой — возвращаем [] без вызова API.
    Если после фильтрации по threshold не осталось ни одного — возвращаем [].
    """
    if not chunks:
        return []

    logger.info(f"[reranker] Запрос rerank: {len(chunks)} кандидатов → top {top_n}")

    documents = [chunk.content for chunk in chunks]

    results = await asyncio.to_thread(
        _rerank_sync, query, documents, top_n
    )

    reranked: list[RetrievedChunk] = []
    for r in results:
        score = r.relevance_score
        chunk = chunks[r.index]
        logger.info(
            f"[reranker] [{r.index}] score={score:.4f} | {chunk.filename} | {chunk.content[:60]}..."
        )
        if score >= threshold:
            reranked.append(chunk)

    logger.info(f"[reranker] После threshold={threshold}: {len(reranked)} чанков")
    return reranked


def _rerank_sync(query: str, documents: list[str], top_n: int):
    response = _co.rerank(
        model=RERANK_MODEL,
        query=query,
        documents=documents,
        top_n=top_n,
    )
    return response.results