# worker/tasks.py
import logging

from core.classify_intent import classify_intent
from core.other_intent import handle_other_intent
from telegram.telegram_client import send_message
from db import get_or_create_conversation, log_message #### ПОЧЕМУ НЕ ИСПОЛЬЗУЕМ
from core.escalation import create_escalation
from core.groq_errors import GroqRateLimitExhausted
from rag.retrieval import retrieve, intent_to_category
from rag.rag_answer import rag_answer

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

# тот же порог, что и в main.py — если снова не укладываемся, дальше не крутим,
# отдаём оператору. Живёт здесь, а не в main.py, потому что ретрай и
# его лимит — забота воркера, веб-процесс просто ставит задачу в очередь.
RETRY_AFTER_ESCALATION_THRESHOLD = 300  # 5 минут


async def retry_llm_pipeline(
    ctx,
    chat_id: int,
    text: str,
    conversation_id: int,
) -> None:
    """
    Повторяет весь путь classify_intent -> ветка ответа -> send_message.
    Идемпотентно: заново классифицируем, а не тащим старый intent —
    он мог быть определён неверно из-за спешки при первом фейле,
    да и classify тоже мог быть тем, что упало.
    """
    try:
        intent = await classify_intent(text)

        if intent in ESCALATION_INTENTS:
            await create_escalation(conversation_id, intent, text)
            reply = "Передал ваш вопрос специалисту, скоро ответим."


        elif intent in RAG_INTENTS:
            category = intent_to_category(intent)
            chunks = await retrieve(query=text, category=category)
            reply = await rag_answer(query=text, chunks=chunks)

        elif intent == "спам":
            reply = "Если у вас есть конкретный вопрос, сформулируйте его пожалуйста."

        else:
            reply = await handle_other_intent(text)

        await log_message(conversation_id, "assistant", reply)
        await send_message(chat_id, reply)

    except GroqRateLimitExhausted as e:
        if e.retry_after <= RETRY_AFTER_ESCALATION_THRESHOLD:
            logger.warning(f"Повторный rate-limit, ставлю в очередь ещё раз через {e.retry_after}s")
            redis = ctx["redis"]
            await redis.enqueue_job(
                "retry_llm_pipeline",
                chat_id=chat_id,
                text=text,
                conversation_id=conversation_id,
                _defer_by=e.retry_after,
            )
        else:
            logger.warning(f"Повторный rate-limit слишком долгий ({e.retry_after}s), эскалирую")
            await create_escalation(
                conversation_id,
                intent="другое",
                message_text=text,
                reason="llm_unavailable",
            )
            await send_message(chat_id, "Прошу прощения за ожидание — передал ваш вопрос специалисту.")