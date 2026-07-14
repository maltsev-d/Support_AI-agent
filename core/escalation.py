# core/escalation.py
import db

# Маппинг intent → reason для n8n.
# reason — технический ключ по которому n8n маршрутизирует эскалацию
# в нужный поток (оператор доставки, оператор оплаты, общая поддержка).
ESCALATION_REASONS = {
    "жалоба":               "user_complaint",
    "жалоба_по_оплате":     "payment_issue",
    "жалоба_по доставке":   "delivery_issue",
    "техподдержка":         "tech_support",
}


async def create_escalation(
    conversation_id: int,
    intent: str,
    message_text: str,
    reason: str | None = None,   # если передан явно (например "llm_unavailable") — используем его
) -> None:
    # reason из аргумента приоритетнее маппинга — нужен для системных эскалаций
    # типа llm_unavailable которые не связаны с intent пользователя
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