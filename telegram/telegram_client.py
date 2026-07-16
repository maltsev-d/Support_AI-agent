# telegram_client.py
import httpx
from config import settings

BASE = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


async def send_message(chat_id: int, text: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{BASE}/sendMessage",
            json={"chat_id": chat_id, "text": text},
        )
        resp.raise_for_status()


async def answer_callback_query(callback_query_id: str) -> None:
    """Убирает индикатор загрузки с Inline кнопки."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(
            f"{BASE}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
        )

async def send_message_with_inline_button(
    chat_id: int,
    text: str,
    button_text: str,
    callback_data: str,
) -> None:
    keyboard = {
        "inline_keyboard": [[
            {"text": button_text, "callback_data": callback_data}
        ]]
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{BASE}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "reply_markup": keyboard,
            },
        )
        resp.raise_for_status()

async def send_message_with_reply_keyboard(chat_id: int, text: str) -> None:
    """Отправляет сообщение с постоянной кнопкой под полем ввода."""
    keyboard = {
        "keyboard": [["Закрыть диалог"]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "persistent": True,  # ← держит клавиатуру видимой всегда
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{BASE}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "reply_markup": keyboard,
            },
        )
        resp.raise_for_status()


async def remove_reply_keyboard(chat_id: int, text: str) -> None:
    """Убирает Reply Keyboard у оператора."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{BASE}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "reply_markup": {"remove_keyboard": True},
            },
        )
        resp.raise_for_status()