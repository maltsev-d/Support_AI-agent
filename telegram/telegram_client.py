# telegram_client.py
import httpx
from config import settings


async def send_message(chat_id: int, text: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        resp.raise_for_status()