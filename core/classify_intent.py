import json
from groq import AsyncGroq, APIStatusError, APIConnectionError, APITimeoutError
from dotenv import load_dotenv
import logging
from config import settings
from core.groq_errors import GroqRateLimitExhausted, is_rate_limit_error, extract_retry_after

load_dotenv()
logger = logging.getLogger(__name__)# если конфиг логгера ещё нигде в проекте не настраивал (basicConfig),
                                    # добавь один раз в точке входа (main.py),
                                    # иначе warning уйдёт в никуда без хендлера:
                                    # logging.basicConfig(level=logging.INFO)


# groq_client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY")) #v1
groq_client = AsyncGroq(api_key=settings.groq_api_key) #v2-сделали config.py


INTENT_CLASSIFICATION_PROMPT = """Ты классифицируешь сообщения в саппорт-чат компании по импорту оборудования, автомобилей и запчастей из-за границы в Россию.
Верни JSON строго такого формата: {"intent": "категория"}

Категории:
- вопрос_по_продукту: характеристики товара, совместимость, наличие документов/комплектации, локация/реквизиты компании как справочная информация — любой вопрос ДО покупки или не про конкретную проблему
- оплата: всё что касается денег и платежей — способ оплаты, валюта, курс, комиссия, рассрочка, реквизиты для перевода, а также проблемы с уже прошедшей оплатой
- жалоба: недоволен сервисом, качеством, сроками в целом — эмоциональная претензия, не привязанная к одному платежу или техническому дефекту
- техподдержка: оборудование/автомобиль не работает или работает неправильно — не включается, не заводится, ошибка, нужна калибровка/настройка/подключение
- доставка: где груз, статус растаможки, сроки, логистика, самовывоз, доставка
- спам: реклама, боты, нерелевантный текст, заработок/крипта/казино, лиды
- другое: короткие нейтральные реплики без содержательного вопроса — "ок", "спасибо", "ага", приветствия

Примеры:
"какая мощность у станка" → {"intent": "вопрос_по_продукту"}
"в комплекте документы на растаможку есть?" → {"intent": "вопрос_по_продукту"}
"какой у вас юридический адрес" → {"intent": "вопрос_по_продукту"}
"можно оплатить в юанях напрямую?" → {"intent": "оплата"}
"пришлите реквизиты для перевода" → {"intent": "оплата"}
"есть рассрочка или только полная предоплата?" → {"intent": "оплата"}
"списали деньги дважды" → {"intent": "оплата"}
"станок не включается после установки" → {"intent": "техподдержка"}
"двигатель заводится но троит" → {"intent": "техподдержка"}
"как откалибровать после транспортировки" → {"intent": "техподдержка"}
"где мой груз, сколько ждать" → {"intent": "доставка"}
"на какой стадии растаможка" → {"intent": "доставка"}
"третий день жду ответа от поддержки, это ужасно" → {"intent": "жалоба"}
"станок пришёл битый, кто виноват" → {"intent": "жалоба"}
"заработок без вложений, пиши в личку" → {"intent": "спам"}
"спасибо, разобрался" → {"intent": "другое"}
"ага" → {"intent": "другое"}

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
                {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
                {"role": "user", "content": message_text}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=100,
        )
        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        intent = parsed.get("intent", "").strip()

        if intent not in VALID_INTENTS:
            return "другое"
        return intent

    except (json.JSONDecodeError, KeyError):
        logger.warning("Groq вернул кривой JSON, переключаюсь на fallback-модель")
        return await classify_intent_fallback(message_text)

    except (APIStatusError, APIConnectionError, APITimeoutError) as e:
        logger.warning(f"Основная модель недоступна ({e}), переключаюсь на fallback-модель")
        return await classify_intent_fallback(message_text)

    except Exception as e:
        logger.warning(f"Groq classify failed непредвиденно: {e}")
        return "другое"


async def classify_intent_fallback(message_text: str) -> str:
    try:
        response = await groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": INTENT_CLASSIFICATION_PROMPT},
                {"role": "user", "content": message_text}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=100,
        )
        parsed = json.loads(response.choices[0].message.content)
        intent = parsed.get("intent", "").strip()
        return intent if intent in VALID_INTENTS else "другое"
    except Exception as e:
        logger.warning(f"Fallback-модель тоже недоступна ({e}), отдаю 'другое'")
        return "другое"