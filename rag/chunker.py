# rag/chunker.py
"""
ШАГ 4 в pipeline ingestion.

Chunker принимает сырой текст и возвращает список перекрывающихся кусков (чанков).

ЗАЧЕМ ВООБЩЕ РЕЗАТЬ:
LLM и embedding-модели имеют лимит на длину входа (512 токенов у Cohere).
Кроме того, один большой вектор на весь документ теряет детали —
"Автомобили.txt" превратится в вектор "про автомобили вообще", а не про
конкретную модель. Мелкие чанки = точнее находим нужный кусок при поиске.

ЗАЧЕМ OVERLAP:
Если предложение попало на границу чанка — оно разрезано и смысл теряется.
Overlap = повторяем последние ~80 токенов в начале следующего чанка.
Чанк [1] начнётся с последних предложений чанка [0].
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# ОЦЕНКА ТОКЕНОВ:
# Tiktoken (библиотека OpenAI) даёт точный счёт, но скачивает файл при первом запуске.
# Используем грубую оценку: для кириллицы ~2 символа на токен.
# В продакшне замени на:
#   import tiktoken
#   _enc = tiktoken.get_encoding("cl100k_base")
#   def _count_tokens(text): return len(_enc.encode(text))
def _count_tokens(text: str) -> int:
    return max(1, len(text) // 2)


CHUNK_SIZE = 400    # целевой размер чанка в токенах (~800 символов кириллицы)
CHUNK_OVERLAP = 80  # токенов повтора между соседними чанками


@dataclass
class Chunk:
    index: int        # порядковый номер внутри документа (0, 1, 2...)
    content: str      # текст чанка
    token_count: int  # оценочный размер в токенах


def _split_sentences(text: str) -> list[str]:
    """
    Режет текст на предложения.
    Разделители: точка/восклицательный/вопросительный знак + пробел,
    или двойной перенос строки (абзац).
    Пример: "Станок CNC-500. Мощность 7.5 кВт." → ["Станок CNC-500.", "Мощность 7.5 кВт."]
    """
    parts = re.split(r'(?<=[.!?])\s+|\n{2,}', text.strip())
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str) -> list[Chunk]:
    """
    Основная функция чанкера.

    АЛГОРИТМ:
    1. Режем текст на предложения
    2. Накапливаем предложения в буфер (buf) пока не превысим CHUNK_SIZE
    3. Как только превысили — сохраняем буфер как чанк
    4. Откатываемся назад: убираем предложения из начала буфера
       пока оставшийся хвост не станет <= CHUNK_OVERLAP токенов
    5. К этому хвосту добавляем новые предложения — это и есть overlap

    ПРИМЕР:
    buf = ["Станок CNC-500.", "Мощность 7.5 кВт.", "Гарантия 2 года."]  → чанк 0
    откат → buf = ["Гарантия 2 года."]  (overlap)
    buf = ["Гарантия 2 года.", "Цена от 850 000 руб.", ...]  → чанк 1
    """
    sentences = _split_sentences(text)
    if not sentences:
        return []

    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_tokens: int = 0
    chunk_index = 0

    for sentence in sentences:
        s_tokens = _count_tokens(sentence)

        # Одиночное предложение длиннее лимита — берём как есть, не режем.
        # Лучше чуть длинный чанк, чем потерять смысл.
        if s_tokens > CHUNK_SIZE:
            if buf:
                chunks.append(Chunk(chunk_index, " ".join(buf), buf_tokens))
                chunk_index += 1
                buf, buf_tokens = [], 0
            chunks.append(Chunk(chunk_index, sentence, s_tokens))
            chunk_index += 1
            continue

        # Буфер переполнен — сохраняем чанк и делаем откат на overlap
        if buf_tokens + s_tokens > CHUNK_SIZE and buf:
            chunks.append(Chunk(chunk_index, " ".join(buf), buf_tokens))
            chunk_index += 1

            # Убираем предложения с начала пока хвост > CHUNK_OVERLAP
            while buf and buf_tokens > CHUNK_OVERLAP:
                removed = buf.pop(0)
                buf_tokens -= _count_tokens(removed)

        buf.append(sentence)
        buf_tokens += s_tokens

    # Последний буфер — может быть меньше CHUNK_SIZE, это нормально
    if buf:
        chunks.append(Chunk(chunk_index, " ".join(buf), buf_tokens))

    return chunks