# core/escalation.py
import db
from config import settings
import logging

logger = logging.getLogger(__name__)

ESCALATION_REASONS = {
    "жалоба":               "complaint",
    "жалоба_по_оплате":     "payment_issue",
    "жалоба_по доставке":   "delivery_issue",
    "техподдержка":         "support",
}


async def create_escalation(
    conversation_id: int,
    intent: str,
    message_text: str,
    chat_id: int,                # добавили
    reason: str | None = None,
) -> None:
    resolved_reason = reason or ESCALATION_REASONS.get(intent, "manual")
    summary = f"[{intent}] {message_text}"

    async with db.pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO escalations (conversation_id, reason, summary)
            VALUES ($1, $2, $3)
            """,
            conversation_id, resolved_reason, summary,
        )

    await db.update_conversation_status(conversation_id, "escalated")

    # Отправляем на n8n webhook
    import httpx
    payload = {
        "conversation_id": conversation_id,
        "reason": resolved_reason,
        "intent": intent,
        "summary": summary,
        "chat_id": chat_id,
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(settings.n8n_escalation_webhook, json=payload)
    except Exception as e:
        logger.warning(f"[escalation] n8n webhook failed: {e}")