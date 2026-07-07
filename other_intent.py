# core/other_intent.py
from groq import AsyncGroq
from config import settings



groq_client = AsyncGroq(api_key=settings.groq_api_key)

OTHER_INTENT_SYSTEM_PROMPT = """Ты сотрудник поддержки компании по импорту оборудования и автомобилей.
Пользователь написал что-то, не являющееся конкретным вопросом по продукту, оплате, доставке или техподдержке — 
это может быть приветствие, благодарность, или неясная реплика.

Ответь коротко и по-человечески. НЕ отвечай на вопросы о характеристиках товаров, ценах, сроках доставки, 
способах оплаты — если пользователь на самом деле имел в виду один из этих вопросов, просто вежливо уточни,
что именно его интересует, вместо ответа по существу."""

async def handle_other_intent(message_text: str) -> str:
    response = await groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": OTHER_INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": message_text}
        ],
        max_tokens=150,
    )
    return response.choices[0].message.content.strip()