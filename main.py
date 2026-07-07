# main.py
from fastapi import FastAPI, Header, HTTPException
from config import settings
from telegram_models import TelegramUpdate
import hmac
import httpx
from telegram_client import send_message
from classify_intent import classify_intent
app = FastAPI()

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

    intent = await classify_intent(text)
    print(f"chat_id={chat_id} intent={intent} text={text!r}")

    try:
        await send_message(chat_id, f"Понял, это: {intent}")
    except httpx.HTTPStatusError as e:
        print(f"send_message failed: {e}")

    return {"ok": True}