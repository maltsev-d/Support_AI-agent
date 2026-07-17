# main.py
import time
import hmac
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from arq import create_pool
from arq.connections import RedisSettings
from redis.asyncio import Redis as AIORedis
import logging

from config import settings, OPERATOR_CHAT_IDS, OPERATOR_DEFAULT_CHAT_ID
from telegram.telegram_models import TelegramUpdate
from telegram.telegram_client import (
    send_message,
    answer_callback_query,
    send_message_with_reply_keyboard,
    remove_reply_keyboard
)

from core.classify_intent import classify_intent
from core.escalation import create_escalation
from core.other_intent import handle_other_intent
from core.groq_errors import GroqRateLimitExhausted
from db import (
    init_pool,
    close_pool,
    get_or_create_user,
    get_or_create_conversation,
    log_message,
    get_conversation_history,
    take_escalation,
    update_conversation_status,
    resolve_escalation,
)
import db
from rag.retrieval import retrieve, intent_to_category
from rag.rag_answer import rag_answer
from core.redis_session import (
    set_operator_session,
    get_conversation_by_operator,
    get_operator_by_conversation,
    get_client_chat,
    clear_operator_session,
)
from telegram.telegram_client import send_message_with_inline_button
from telegram.telegram_client import download_voice
from core.whisper import transcribe_voice, WHISPER_UNAVAILABLE_REPLY

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

# Если retry_after больше порога — не ждём, сразу к оператору
RETRY_AFTER_ESCALATION_THRESHOLD = 300

# Диалог закрывается если 24 часа не было сообщений
RESOLVE_AFTER_SECONDS = 24 * 60 * 60

redis_client: AIORedis | None = None
arq_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global arq_pool, redis_client
    try:
        print("[lifespan] Инициализирую БД пул...")
        await init_pool()
        print("[lifespan] БД пул создан")

        print("[lifespan] Инициализирую ARQ пул...")
        arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        print("[lifespan] ARQ пул создан")

        print("[lifespan] Инициализирую Redis клиент...")
        redis_client = AIORedis.from_url(settings.redis_url, decode_responses=True)
        print("[lifespan] Redis клиент создан")

        print("[lifespan] Инициализирую Drive Watch...")
        await _init_drive_watch()
        print("[lifespan] Drive Watch готов")

    except Exception as e:
        print(f"[lifespan] ОШИБКА при инициализации: {e}")
        import traceback
        traceback.print_exc()
        raise

    yield

    try:
        await close_pool()
        await redis_client.aclose()
    except Exception as e:
        print(f"[lifespan] Ошибка при shutdown: {e}")


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.head("/health")
async def health_head():
    return {"status": "ok"}

@app.post("/drive/webhook")
async def drive_webhook(
    request: Request,
    token: str | None = None,
):
    # Верификация секрета
    if not hmac.compare_digest(token or "", settings.google_webhook_secret):
        raise HTTPException(status_code=403, detail="Invalid token")

    # sync — первое уведомление при создании подписки, игнорируем
    resource_state = request.headers.get("X-Goog-Resource-State", "")
    if resource_state == "sync":
        return {"ok": True}

    # Реальное изменение — кидаем в ARQ и сразу отвечаем 200
    await arq_pool.enqueue_job("process_drive_changes")
    return {"ok": True}

@app.post("/conversation/{conversation_id}/resolve")
async def resolve_conversation(conversation_id: int):
    """
    Endpoint для n8n: оператор закрыл эскалацию вручную.
    n8n дёргает этот URL после обработки тикета.
    """
    from db import update_conversation_status, resolve_escalation
    await update_conversation_status(conversation_id, "resolved")
    await resolve_escalation(conversation_id)  # добавить
    return {"ok": True, "conversation_id": conversation_id, "status": "resolved"}


@app.post("/webhook")
async def webhook(
        update: TelegramUpdate,
        x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if not hmac.compare_digest(
            x_telegram_bot_api_secret_token or "",
            settings.telegram_webhook_secret,
    ):
        raise HTTPException(status_code=403, detail="Invalid secret token")

    # ── ВЕТКА 1: callback_query ──
    if update.callback_query:
        cq = update.callback_query
        data = cq.data or ""
        sender_id = cq.from_user.id if cq.from_user else None

        if data.startswith("escalate:") and sender_id:
            conversation_id = int(data.split(":")[1])
            client_chat_id = cq.message.chat.id

            # Сначала отвечаем на callback — иначе Telegram будет повторять запрос
            await answer_callback_query(cq.id)

            await create_escalation(
                conversation_id,
                intent="другое",
                message_text="Клиент запросил соединение с оператором",
                chat_id=client_chat_id,
                reason="manual",
            )
            await send_message(client_chat_id, "Соединяю вас со специалистом, ожидайте.")

        elif data.startswith("take:") and sender_id:
            operator_chat_id = sender_id
            parts = data.split(":")
            conversation_id = int(parts[1])
            client_chat_id = int(parts[2])

            # Сначала отвечаем на callback
            await answer_callback_query(cq.id)

            await take_escalation(conversation_id)
            await set_operator_session(
                redis_client, operator_chat_id, conversation_id, client_chat_id
            )
            await send_message_with_reply_keyboard(
                operator_chat_id,
                f"✅ Взяли в работу диалог #{conversation_id}.\nВаши сообщения идут клиенту.",
            )

        return {"ok": True}

    if not update.message or not update.message.text:
        return {"ok": True}

    text = update.message.text
    chat_id = update.message.chat.id

    print(f"[webhook] chat_id={chat_id} text={text!r}")

    # ── ВЕТКА 2: сообщение от оператора ──
    all_operator_ids = set(OPERATOR_CHAT_IDS.values()) | {OPERATOR_DEFAULT_CHAT_ID}
    if chat_id in all_operator_ids:
        if text == "Закрыть диалог":
            conversation_id = await get_conversation_by_operator(redis_client, chat_id)
            if conversation_id:
                client_chat_id = await get_client_chat(redis_client, conversation_id)
                await clear_operator_session(redis_client, chat_id, conversation_id)
                await update_conversation_status(conversation_id, "resolved")
                await resolve_escalation(conversation_id)
                await remove_reply_keyboard(chat_id, "Диалог закрыт.")
                if client_chat_id:
                    await send_message(
                        int(client_chat_id),
                        "Вопрос решён. Если появятся новые вопросы — пишите.",
                    )
            else:
                await send_message(chat_id, "Нет активного диалога.")
        else:
            conversation_id = await get_conversation_by_operator(redis_client, chat_id)
            if conversation_id:
                client_chat_id = await get_client_chat(redis_client, conversation_id)
                if client_chat_id:
                    await send_message(int(client_chat_id), text)
                    await log_message(int(conversation_id), "operator", text)
            else:
                await send_message(chat_id, "Нет активного диалога.")

        return {"ok": True}

    # ── ВЕТКА 3: клиент в escalated диалоге ──
    user_id = await get_or_create_user(chat_id, username=None)

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, status
               FROM conversations
               WHERE user_id = $1
               ORDER BY created_at DESC LIMIT 1""",
            user_id,
        )

    if row and row["status"] == "escalated":
        await log_message(row["id"], "user", text)
        operator_chat_id = await get_operator_by_conversation(redis_client, row["id"])
        if operator_chat_id:
            await send_message(int(operator_chat_id), f"👤 Клиент: {text}")
        return {"ok": True}

    # ── Обычный пайплайн (active диалог) ──
    conversation_id = await get_or_create_conversation(user_id)

    # ── /start ──────────────────────────────────────────────────
    if text.strip() == "/start":
        await send_message(chat_id, (
            "Привет! Я виртуальный помощник службы поддержки.\n"
            "Помогу с вопросами о товарах, доставке, оплате и работе компании.\n\n"
            "Просто напишите ваш вопрос — отвечу сразу."
        ))
        return {"ok": True}

    user_message_logged = False
    message_sent = False

    # Голосовое сообщение
    if update.message.voice:
        try:
            audio_bytes = await download_voice(update.message.voice.file_id)
            text = await transcribe_voice(audio_bytes)
            if not text:
                await send_message(chat_id, WHISPER_UNAVAILABLE_REPLY)
                return {"ok": True}
        except GroqRateLimitExhausted:
            await send_message(chat_id, WHISPER_UNAVAILABLE_REPLY)
            return {"ok": True}

    try:
        intent = await classify_intent(text)
        history = await get_conversation_history(conversation_id)
        await log_message(conversation_id, "user", text, intent)
        user_message_logged = True

        if intent in ESCALATION_INTENTS:
            await create_escalation(conversation_id, intent, text, chat_id=chat_id)
            reply = "Передал ваш вопрос специалисту, скоро ответим."

        elif intent in RAG_INTENTS:
            category = intent_to_category(intent)
            chunks = await retrieve(query=text, category=category)
            reply = await rag_answer(query=text, chunks=chunks, history=history)

            # убрать `or True` после тестирования
            if not chunks:
                await send_message_with_inline_button(
                    chat_id,
                    reply,
                    button_text="👤 Соединить с оператором",
                    callback_data=f"escalate:{conversation_id}",
                )
                message_sent = True
            else:
                await send_message(chat_id, reply)
                message_sent = True

        elif intent == "спам":
            reply = "Если у вас есть конкретный вопрос, сформулируйте его пожалуйста."

        else:
            reply = await handle_other_intent(text, history=history)

        await log_message(conversation_id, "assistant", reply)

        if intent not in ESCALATION_INTENTS:
            await arq_pool.enqueue_job(
                "mark_resolved",
                conversation_id=conversation_id,
                scheduled_at=time.time(),
                _defer_by=RESOLVE_AFTER_SECONDS,
            )

        if not message_sent:
            try:
                await send_message(chat_id, reply)
            except httpx.HTTPStatusError as e:
                print(f"[webhook] send_message failed: {e}")

    except GroqRateLimitExhausted as e:
        if not user_message_logged:
            await log_message(conversation_id, "user", text, intent=None)

        if e.retry_after <= RETRY_AFTER_ESCALATION_THRESHOLD:
            await arq_pool.enqueue_job(
                "retry_llm_pipeline",
                chat_id=chat_id,
                text=text,
                conversation_id=conversation_id,
                _defer_by=e.retry_after,
            )
            stub_reply = "Сейчас все операторы заняты, отвечу через пару минут."
            try:
                await send_message(chat_id, stub_reply)
            except httpx.HTTPStatusError as send_err:
                print(f"[webhook] send_message failed: {send_err}")
        else:
            await create_escalation(
                conversation_id,
                intent="другое",
                message_text=text,
                chat_id=chat_id,
                reason="llm_unavailable",
            )
            fallback_reply = "Прошу прощения за ожидание — передал ваш вопрос специалисту."
            await log_message(conversation_id, "assistant", fallback_reply)
            try:
                await send_message(chat_id, fallback_reply)
            except httpx.HTTPStatusError as send_err:
                print(f"[webhook] send_message failed: {send_err}")

    return {"ok": True}

@app.delete("/drive/categories/{category}")
async def delete_drive_category(category: str, confirm: bool = False):
    """
    Удаляет все документы и чанки категории из БД.
    Без confirm=true — только показывает что будет удалено.
    """
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, document_id, filename FROM documents WHERE category = $1",
            category,
        )

    if not rows:
        return {"category": category, "documents": 0, "message": "Ничего не найдено"}

    if not confirm:
        return {
            "category": category,
            "documents": len(rows),
            "files": [r["filename"] for r in rows],
            "message": "Передайте confirm=true для удаления",
        }

    async with db.pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM documents WHERE category = $1",
            category,
        )

    return {"category": category, "deleted": len(rows), "ok": True}

async def _init_drive_watch() -> None:
    """
    Вызывается при старте FastAPI.
    Проверяет pageToken и Watch подписки — создаёт если нет или истекли.
    """
    import uuid
    from datetime import datetime, timezone
    from rag.drive_client import get_start_page_token, watch_folder
    from db import get_active_watch_channels, upsert_watch_channel
    from config import DRIVE_FOLDER_MAP, settings

    # pageToken
    existing_token = await redis_client.get("drive:page_token")
    if not existing_token:
        token = await get_start_page_token()
        await redis_client.set("drive:page_token", token)
        logger.info(f"[drive_init] pageToken установлен: {token}")
    else:
        logger.info(f"[drive_init] pageToken уже есть в Redis")
    # Watch подписки
    active = await get_active_watch_channels()
    active_folders = {ch["folder_id"] for ch in active}

    webhook_url = f"https://{settings.render_app_url}drive/webhook?token={settings.google_webhook_secret}"

    for category, folder_id in DRIVE_FOLDER_MAP.items():
        if folder_id in active_folders:
            logger.info(f"[drive_init] подписка для {category} уже активна")
            continue

        channel_id = str(uuid.uuid4())
        response = await watch_folder(folder_id, webhook_url, channel_id)
        expires_at = datetime.fromtimestamp(
            int(response["expiration"]) / 1000,
            tz=timezone.utc,
        )
        await upsert_watch_channel(
            folder_id=folder_id,
            category=category,
            channel_id=channel_id,
            resource_id=response["resourceId"],
            expires_at=expires_at,
        )
        logger.info(f"[drive_init] подписка создана для {category}")