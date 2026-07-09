# main.py
from fastapi import FastAPI, Header, HTTPException
from config import settings
from telegram.telegram_models import TelegramUpdate
import hmac
import httpx
from telegram.telegram_client import send_message
from core.classify_intent import classify_intent
from contextlib import asynccontextmanager
from db import init_pool, close_pool, get_or_create_user, get_or_create_conversation, log_message
from core.escalation import create_escalation
from core.other_intent import handle_other_intent
from core.groq_errors import GroqRateLimitExhausted
from arq import create_pool
from arq.connections import RedisSettings

ESCALATION_INTENTS = {"жалоба", "оплата", "доставка"}
RAG_INTENTS = {"вопрос_по_продукту","вопрос_по_компании", "техподдержка"}

# порог согласован с worker/tasks.py: за ним фоновый ретрай не имеет смысла —
# юзер не должен ждать ответа дольше 5 минут, эскалируем оператору сразу
RETRY_AFTER_ESCALATION_THRESHOLD = 300

arq_pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global arq_pool
    await init_pool()
    arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    yield
    await close_pool()
app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    return {"status": "ok"}
@app.head("/health")
async def health():
    return {"status": "ok"}

@app.post("/webhook")
async def webhook(
    update: TelegramUpdate,
    x_telegram_bot_api_secret_token: str | None = Header(default=None)
):
    if not hmac.compare_digest(
            x_telegram_bot_api_secret_token or "",
            settings.telegram_webhook_secret
    ):
        raise HTTPException(status_code=403, detail="Invalid secret token")

    if update.message and update.message.text:
        print(f"[webhook] chat_id={update.message.chat.id} text={update.message.text!r}")
    else:
        print(f"[webhook] update_id={update.update_id} non-text or empty payload")

    text = update.message.text
    chat_id = update.message.chat.id
    telegram_id = update.message.chat.id  # для приватных чатов chat.id == user.id

    user_id = await get_or_create_user(telegram_id, username=None)
    conversation_id = await get_or_create_conversation(user_id)

    try:
        intent = await classify_intent(text)
        await log_message(conversation_id, "user", text, intent)

        if intent in ESCALATION_INTENTS:
            await create_escalation(conversation_id, intent, text)
            reply = "Передал ваш вопрос специалисту, скоро ответим."

        elif intent in RAG_INTENTS:
            reply = f"[RAG] это: {intent}"

        elif intent == "спам":
            reply = "Если у вас есть конкретный вопрос, сформулируйте его пожалуйста."

        else:
            reply = await handle_other_intent(text)

        await log_message(conversation_id, "assistant", reply)

        try:
            await send_message(chat_id, reply)
        except httpx.HTTPStatusError as e:
            print(f"send_message failed: {e}")

    except GroqRateLimitExhausted as e:
        # classify_intent мог упасть до логирования user-сообщения —
        # логируем здесь без intent, чтобы след в БД не потерялся
        await log_message(conversation_id, "user", text, intent=None)

        if e.retry_after <= RETRY_AFTER_ESCALATION_THRESHOLD:
            await arq_pool.enqueue_job(
                "retry_llm_pipeline",
                chat_id=chat_id,
                text=text,
                conversation_id=conversation_id,
                _defer_by=e.retry_after,
            )
            stub_reply = "Сейчас все операторы и модели заняты, отвечу через пару минут."
            await log_message(conversation_id, "assistant", stub_reply)
            try:
                await send_message(chat_id, stub_reply)
            except httpx.HTTPStatusError as send_err:
                print(f"send_message failed: {send_err}")
        else:
            await create_escalation(
                conversation_id,
                intent="другое",
                message_text=text,
                reason="llm_unavailable",
            )
            fallback_reply = "Прошу прощения за ожидание — передал ваш вопрос специалисту."
            await log_message(conversation_id, "assistant", fallback_reply)
            try:
                await send_message(chat_id, fallback_reply)
            except httpx.HTTPStatusError as send_err:
                print(f"send_message failed: {send_err}")

    return {"ok": True}