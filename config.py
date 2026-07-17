# config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    groq_api_key: str
    telegram_bot_token: str
    telegram_webhook_secret: str
    database_url: str
    redis_url: str
    cohere_api_key: str
    n8n_escalation_webhook: str
    google_credentials: str
    google_webhook_secret: str
    render_app_url: str

    def __post_init__(self):
        missing = [k for k, v in self.__dict__.items() if not v]
        if missing:
            raise RuntimeError(f"Missing env vars: {missing}")

def _load() -> Settings:
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
        database_url=os.getenv("DATABASE_URL", ""),
        redis_url=os.getenv("REDIS_URL", ""),
        cohere_api_key=os.getenv("COHERE_API_KEY", ""),   # ← новое
        n8n_escalation_webhook = os.getenv("N8N_ESCALATION_WEBHOOK", ""),
        google_credentials=os.getenv("GOOGLE_CREDENTIALS", ""),
        google_webhook_secret=os.getenv("DRIVE_WEBHOOK_SECRET", ""),
        render_app_url=os.getenv("RENDER_APP_URL", ""),


    )

settings = _load()

# Хардкод операторов: reason → telegram chat_id оператора
# "остальные" (complaint, manual, llm_unavailable) → дефолтный оператор
OPERATOR_CHAT_IDS: dict[str, int] = {
    "delivery_issue": 5605852182,   # ← подставь реальные chat_id
    "payment_issue":  5605852182,
    "support":        5605852182,
}
OPERATOR_DEFAULT_CHAT_ID: int = 5605852182  # complaint, manual, llm_unavailable

DRIVE_FOLDER_MAP: dict[str, str] = {
    "company":  "1zUN-h0h3P61Xn0lVLtmBERMEOKglZ0fU",
    "products": "1imceI6V2ZTluHetZESzeVlTFNVtLtkIA",
    "delivery": "1I5Y_pDk7SIZmnVDD_D8hc83N_aR95k3h",
    "payments": "1vcPRGbYEYD8C3yurzekJ4vtaEXknY5Qt",
}
# Обратный маппинг — folder_id → category, нужен при обработке Watch уведомлений
DRIVE_FOLDER_CATEGORY: dict[str, str] = {v: k for k, v in DRIVE_FOLDER_MAP.items()}