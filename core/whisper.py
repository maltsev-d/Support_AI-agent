# core/whisper.py
import io
import logging
from groq import AsyncGroq
from config import settings
from core.groq_errors import GroqRateLimitExhausted, is_rate_limit_error, extract_retry_after

logger = logging.getLogger(__name__)
_groq = AsyncGroq(api_key=settings.groq_api_key)

WHISPER_UNAVAILABLE_REPLY = "Не могу обработать голосовое сообщение, напишите текстом."


async def transcribe_voice(audio_bytes: bytes) -> str | None:
    """
    Транскрибирует голосовое сообщение через Groq Whisper.
    Возвращает текст или None если не удалось.

    ПОЧЕМУ io.BytesIO с именем:
    Groq SDK ожидает файлоподобный объект с атрибутом name —
    по нему определяет формат. Без имени упадёт с ошибкой формата.
    """
    try:
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = "voice.ogg"

        transcription = await _groq.audio.transcriptions.create(
            file=audio_file,
            model="whisper-large-v3-turbo",
            language="ru",
            response_format="text",
        )
        text = transcription.strip()
        logger.info(f"[whisper] транскрибировано: '{text[:80]}'")
        return text if text else None

    except Exception as e:
        if is_rate_limit_error(e):
            raise GroqRateLimitExhausted(retry_after=extract_retry_after(e)) from e
        logger.warning(f"[whisper] ошибка транскрибации: {e}")
        return None