# core/redis_session.py
"""
Хранит временные сессии оператор ↔ клиент в Redis.

Две связи для быстрого поиска в обе стороны:
  operator_session:{operator_chat_id} → conversation_id
  operator_active:{conversation_id}   → operator_chat_id

TTL 24 часа — страховка от зависших сессий если оператор
не закрыл диалог явно.
"""
from redis.asyncio import Redis

SESSION_TTL = 86400  # 24 часа


async def set_operator_session(
    redis: Redis,
    operator_chat_id: int,
    conversation_id: int,
    client_chat_id: int,
) -> None:
    pipe = redis.pipeline()
    pipe.setex(f"operator_session:{operator_chat_id}", SESSION_TTL, conversation_id)
    pipe.setex(f"operator_active:{conversation_id}", SESSION_TTL, operator_chat_id)
    pipe.setex(f"client_chat:{conversation_id}", SESSION_TTL, client_chat_id)
    await pipe.execute()


async def get_conversation_by_operator(
    redis: Redis,
    operator_chat_id: int,
) -> int | None:
    val = await redis.get(f"operator_session:{operator_chat_id}")
    return int(val) if val else None


async def get_operator_by_conversation(
    redis: Redis,
    conversation_id: int,
) -> int | None:
    val = await redis.get(f"operator_active:{conversation_id}")
    return int(val) if val else None


async def get_client_chat(
    redis: Redis,
    conversation_id: int,
) -> int | None:
    val = await redis.get(f"client_chat:{conversation_id}")
    return int(val) if val else None


async def clear_operator_session(
    redis: Redis,
    operator_chat_id: int,
    conversation_id: int,
) -> None:
    pipe = redis.pipeline()
    pipe.delete(f"operator_session:{operator_chat_id}")
    pipe.delete(f"operator_active:{conversation_id}")
    pipe.delete(f"client_chat:{conversation_id}")
    await pipe.execute()