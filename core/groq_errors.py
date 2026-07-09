# core/groq_errors.py
import re
from groq import APIStatusError

# Groq возвращает текст вида:
# "Please try again in 3m36.864s" или "Please try again in 827ms" / "in 5s"
_RETRY_PATTERN = re.compile(r"try again in (?:(\d+)m)?([\d.]+)s")


class GroqRateLimitExhausted(Exception):
    """Обе модели (70b и fallback 8b) упёрлись в rate-limit/TPD одновременно."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Groq rate limit exhausted, retry_after={retry_after}s")


def is_rate_limit_error(exc: Exception) -> bool:
    """
    Groq не разводит TPD и обычный per-minute rate-limit отдельным кодом —
    оба падают как APIStatusError 429 с error.code == 'rate_limit_exceeded'.
    Разница видна только в тексте message (число секунд).
    """
    return (
        isinstance(exc, APIStatusError)
        and exc.status_code == 429
    )


def extract_retry_after(exc: Exception) -> float:
    """
    Достаёт число секунд из 'Please try again in 3m36.864s'.
    Если распарсить не удалось — считаем это худшим случаем (сразу эскалация),
    а не тихо ретраим неизвестно сколько.
    """
    message = str(exc)
    match = _RETRY_PATTERN.search(message)
    if not match:
        return float("inf")

    minutes_str, seconds_str = match.groups()
    minutes = int(minutes_str) if minutes_str else 0
    seconds = float(seconds_str)
    return minutes * 60 + seconds