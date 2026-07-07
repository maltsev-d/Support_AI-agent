# main.py
from fastapi import FastAPI, Header, HTTPException
from config import settings
from telegram_models import TelegramUpdate
import hmac
import httpx
from telegram_client import send_message
from classify_intent import classify_intent
from contextlib import asynccontextmanager
from db import init_pool, close_pool, get_or_create_user, get_or_create_conversation, log_message
from escalation import create_escalation
from other_intent import handle_other_intent

ESCALATION_INTENTS = {"жалоба", "оплата"}
RAG_INTENTS = {"вопрос_по_продукту", "техподдержка", "доставка"}

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_pool()
    yield
    await close_pool()
app = FastAPI(lifespan=lifespan)

@app.get("/health")
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

    intent = await classify_intent(text)
    user_id = await get_or_create_user(telegram_id, username=None)
    conversation_id = await get_or_create_conversation(user_id)

    await log_message(conversation_id, "user", text, intent)

    if intent in ESCALATION_INTENTS:
        await create_escalation(conversation_id, intent, text)
        reply = "Передал ваш вопрос специалисту, скоро ответим."

    elif intent in RAG_INTENTS:
        reply = f"[RAG-заглушка] Понял, это: {intent}"

    elif intent == "спам":
        reply = "Если у вас есть конкретный вопрос, сформулируйте его пожалуйста."

    else:
        reply = await handle_other_intent(text)

    await log_message(conversation_id, "assistant", reply)

    try:
        await send_message(chat_id, reply)
    except httpx.HTTPStatusError as e:
        print(f"send_message failed: {e}")

    return {"ok": True}