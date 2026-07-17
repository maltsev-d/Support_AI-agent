# telegram_models.py
from pydantic import BaseModel, Field

class TelegramChat(BaseModel):
    id: int

class TelegramMessage(BaseModel):
    message_id: int
    text: str | None = None
    chat: TelegramChat
    voice: TelegramVoice | None = None

class TelegramUser(BaseModel):
    id: int

class TelegramCallbackQuery(BaseModel):
    id: str
    from_user: TelegramUser | None = Field(None, alias="from")
    message: TelegramMessage | None = None
    data: str | None = None

    model_config = {"populate_by_name": True}

class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None
    callback_query: TelegramCallbackQuery | None = None

class TelegramMessage(BaseModel):
    message_id: int
    text: str | None = None
    chat: TelegramChat
    voice: TelegramVoice | None = None  # ← добавить