import json
from groq import AsyncGroq
from dotenv import load_dotenv
import os
import logging

load_dotenv()
logger = logging.getLogger(__name__)# если конфиг логгера ещё нигде в проекте не настраивал (basicConfig),
                                    # добавь один раз в точке входа (main.py),
                                    # иначе warning уйдёт в никуда без хендлера:
                                    # logging.basicConfig(level=logging.INFO)


# groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY")) #v1
groq_client = AsyncGroq(api_key=settings.groq_api_key) #v2-сделали config.py


INTENT_SYSTEM_PROMPT = """Ты классифицируешь сообщения в саппорт-чат интернет-магазина.
Верни JSON строго такого формата: {"intent": "категория"}

Категории:
- вопрос_по_продукту: как что-то сделать, как работает функция, что входит в тариф
- оплата: конкретная проблема с платежом — списали не то, не прошла оплата, вернуть деньги
- жалоба: недоволен сервисом/качеством, не про конкретный платёж
- техподдержка: не работает функция/баг/ошибка в приложении
- доставка: где заказ, статус отправки, сроки
- спам: реклама, боты, нерелевантный текст
- другое: всё что не подходит выше

Примеры:
"как оплатить картой" → {"intent": "вопрос_по_продукту"}
"списали деньги дважды" → {"intent": "оплата"}
"деньги списали а заказ не пришёл" → {"intent": "доставка"}
"третий день жду ответа от поддержки, это ужасно" → {"intent": "жалоба"}
"приложение крашится при входе" → {"intent": "техподдержка"}

Верни ТОЛЬКО JSON, без markdown, без пояснений."""

VALID_INTENTS = {
    "вопрос_по_продукту", "оплата", "жалоба",
    "техподдержка", "доставка", "спам", "другое"
}

async def classify_intent(message_text: str) -> str:
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": INTENT_SYSTEM_PROMPT},
                {"role": "user", "content": message_text}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=50,
        )
        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        intent = parsed.get("intent", "").strip()

        if intent not in VALID_INTENTS:
            return "другое"  # модель выдумала категорию — fallback, не крашимся
        return intent

    except (json.JSONDecodeError, KeyError):
        # llama-3.1-8b-instant как запасная, если основная модель сломала JSON
        return await classify_intent_fallback(message_text)
    except Exception as e:
        # rate limit / API down — не роняем весь пайплайн из-за классификатора
        logger.warning(f"Groq classify failed: {e}")
        return "другое"


async def classify_intent_fallback(message_text: str) -> str:
    response = await groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": message_text}
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
        max_tokens=50,
    )
    try:
        parsed = json.loads(response.choices[0].message.content)
        intent = parsed.get("intent", "").strip()
        return intent if intent in VALID_INTENTS else "другое"
    except Exception:
        return "другое"