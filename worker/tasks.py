# worker/tasks.py
import logging
import time

from core.classify_intent import classify_intent
from core.other_intent import handle_other_intent
from telegram.telegram_client import send_message
from db import log_message, update_conversation_status, get_conversation_history
from core.escalation import create_escalation
from core.groq_errors import GroqRateLimitExhausted
from rag.retrieval import retrieve, intent_to_category
from rag.rag_answer import rag_answer
import db

logger = logging.getLogger(__name__)

ESCALATION_INTENTS = {
    "техподдержка",
    "жалоба_по доставке",
    "жалоба_по_оплате",
    "жалоба",
}

RAG_INTENTS = {
    "вопрос_по_продукту",
    "вопрос_по_компании",
    "вопрос_по_доставке",
    "вопрос_по_оплате",
}

RETRY_AFTER_ESCALATION_THRESHOLD = 300


async def retry_llm_pipeline(
    ctx,
    chat_id: int,
    text: str,
    conversation_id: int,
) -> None:
    try:
        intent = await classify_intent(text)
        history = await get_conversation_history(conversation_id)  # ← добавили

        if intent in ESCALATION_INTENTS:
            await create_escalation(conversation_id, intent, text, chat_id=chat_id)
            reply = "Передал ваш вопрос специалисту, скоро ответим."

        elif intent in RAG_INTENTS:
            category = intent_to_category(intent)
            chunks = await retrieve(query=text, category=category)
            reply = await rag_answer(query=text, chunks=chunks, history=history)  # ← пробросили

        elif intent == "спам":
            reply = "Если у вас есть конкретный вопрос, сформулируйте его пожалуйста."

        else:
            reply = await handle_other_intent(text, history=history)  # ← пробросили

        await log_message(conversation_id, "assistant", reply)
        await send_message(chat_id, reply)

    except GroqRateLimitExhausted as e:
        if e.retry_after <= RETRY_AFTER_ESCALATION_THRESHOLD:
            logger.warning(f"Повторный rate-limit, ретрай через {e.retry_after}s")
            redis = ctx["redis"]
            await redis.enqueue_job(
                "retry_llm_pipeline",
                chat_id=chat_id,
                text=text,
                conversation_id=conversation_id,
                _defer_by=e.retry_after,
            )
        else:
            logger.warning(f"Rate-limit слишком долгий ({e.retry_after}s), эскалирую")
            await create_escalation(
                conversation_id,
                intent="другое",
                message_text=text,
                chat_id=chat_id,
                reason="llm_unavailable",
            )
            await send_message(
                chat_id,
                "Прошу прощения за ожидание — передал ваш вопрос специалисту.",
            )


async def mark_resolved(
    ctx,
    conversation_id: int,
    scheduled_at: float,  # unix timestamp момента постановки задачи
) -> None:
    """
    Переводит диалог в resolved если после постановки задачи
    не было новых сообщений.

    Логика вместо отмены ARQ задачи:
    ARQ не поддерживает отмену задач по ID. Вместо этого при срабатывании
    проверяем last_message_at — если оно позже scheduled_at, значит пришли
    новые сообщения и диалог трогать не нужно. main.py поставит новую
    mark_resolved задачу при следующем ответе.
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_message_at, status FROM conversations WHERE id = $1",
            conversation_id,
        )

    if not row:
        logger.warning(f"[mark_resolved] conversation {conversation_id} не найден")
        return

    if row["status"] != "active":
        # Диалог уже escalated или resolved — не трогаем
        logger.info(f"[mark_resolved] conversation {conversation_id} статус={row['status']}, пропускаем")
        return

    last_message_ts = row["last_message_at"].timestamp()
    if last_message_ts > scheduled_at:
        # После постановки задачи пришли новые сообщения — не закрываем.
        # main.py при следующем ответе поставит новую задачу mark_resolved.
        logger.info(
            f"[mark_resolved] conversation {conversation_id}: "
            f"новые сообщения после scheduled_at, пропускаем"
        )
        return

    await update_conversation_status(conversation_id, "resolved")
    logger.info(f"[mark_resolved] conversation {conversation_id} → resolved")