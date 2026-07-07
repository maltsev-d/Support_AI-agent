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

async def log_message(conversation_id: int, role: str, content: str, intent: str | None = None) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, intent)
            VALUES ($1, $2, $3, $4)
            """,
            conversation_id, role, content, intent,
        )
        await conn.execute(
            "UPDATE conversations SET last_message_at = now() WHERE id = $1",
            conversation_id,
        )


async def close_pool() -> None:
    if pool:
        await pool.close()