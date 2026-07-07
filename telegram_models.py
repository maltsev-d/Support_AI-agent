# telegram_models.py
from pydantic import BaseModel

class TelegramChat(BaseModel):
    id: int

class TelegramMessage(BaseModel):
    message_id: int
    text: str | None = None
    chat: TelegramChat

class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None