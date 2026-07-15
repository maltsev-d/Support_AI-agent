# db.py
import asyncpg
from config import settings

pool: asyncpg.Pool | None = None

async def init_pool() -> None:
    global pool
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=3,
        command_timeout=10,
    )

async def get_or_create_user(telegram_id: int, username: str | None) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE telegram_id = $1",
            telegram_id,
        )
        if row:
            return row["id"]
        row = await conn.fetchrow(
            "INSERT INTO users (telegram_id, username) VALUES ($1, $2) RETURNING id",
            telegram_id, username,
        )
        return row["id"]

async def get_or_create_conversation(user_id: int) -> int:
    """
    Возвращает активный диалог или создаёт новый.
    Новый создаётся только если нет активного — статусы escalated/resolved
    не мешают созданию нового диалога.
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM conversations WHERE user_id = $1 AND status = 'active'",
            user_id,
        )
        if row:
            return row["id"]
        row = await conn.fetchrow(
            "INSERT INTO conversations (user_id) VALUES ($1) RETURNING id",
            user_id,
        )
        return row["id"]

async def update_conversation_status(conversation_id: int, status: str) -> None:
    """
    Переводит диалог в новый статус.
    active → escalated: при создании эскалации
    active → resolved: по таймауту (ARQ mark_resolved) или вручную через n8n
    escalated → resolved: оператор закрыл через /conversation/{id}/resolve
    """
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversations SET status = $1 WHERE id = $2",
            status, conversation_id,
        )

async def get_conversation_history(
    conversation_id: int,
    limit: int = 6,
) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT role, content FROM messages
            WHERE conversation_id = $1
              AND role IN ('user', 'assistant')
            ORDER BY created_at DESC
            LIMIT $2
            """,
            conversation_id, limit,
        )
    # Разворачиваем: БД вернула новые→старые, LLM ждёт старые→новые
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

async def take_escalation(conversation_id: int) -> None:
    """Оператор взял эскалацию в работу: pending → active."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE escalations
            SET status = 'active'
            WHERE conversation_id = $1 AND status = 'pending'
            """,
            conversation_id,
        )

async def log_message(
    conversation_id: int,
    role: str,
    content: str,
    intent: str | None = None,
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, intent)
            VALUES ($1, $2, $3, $4)
            """,
            conversation_id, role, content, intent,
        )
        # last_message_at — ключевое поле для mark_resolved:
        # если оно обновилось после постановки задачи, значит пришли
        # новые сообщения и закрывать диалог не нужно
        await conn.execute(
            "UPDATE conversations SET last_message_at = now() WHERE id = $1",
            conversation_id,
        )

async def resolve_escalation(conversation_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE escalations
            SET status = 'handled', handled_at = now()
            WHERE conversation_id = $1 AND status = 'pending'
            """,
            conversation_id,
        )

async def close_pool() -> None:
    if pool:
        await pool.close()