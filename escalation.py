# core/escalation.py — пока кладём в корень, structure разберём после
import json
from db import pool

ESCALATION_REASONS = {
    "жалоба": "user_angry",
    "оплата": "payment_issue",
}


async def create_escalation(conversation_id: int, intent: str, message_text: str) -> None:
    reason = ESCALATION_REASONS.get(intent, "manual")
    summary = f"[{intent}] {message_text}"

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO escalations (conversation_id, reason, summary)
            VALUES ($1, $2, $3)
            """,
            conversation_id, reason, summary,
        )