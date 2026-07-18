# worker/tasks.py
import logging
import time

from core.classify_intent import classify_intent
from core.other_intent import handle_other_intent
from telegram.telegram_client import send_message
from db import log_message, update_conversation_status, get_conversation_history
from core.escalation import create_escalation
from core.groq_errors import GroqRateLimitExhausted
from rag.retrieval import retrieve, intent_to_category
from rag.rag_answer import rag_answer
import db

logger = logging.getLogger(__name__)

ESCALATION_INTENTS = {
    "техподдержка",
    "жалоба_по доставке",
    "жалоба_по_оплате",
    "жалоба",
}

RAG_INTENTS = {
    "вопрос_по_продукту",
    "вопрос_по_компании",
    "вопрос_по_доставке",
    "вопрос_по_оплате",
}

RETRY_AFTER_ESCALATION_THRESHOLD = 300


async def retry_llm_pipeline(
    ctx,
    chat_id: int,
    text: str,
    conversation_id: int,
) -> None:
    try:
        intent = await classify_intent(text)
        history = await get_conversation_history(conversation_id)  # ← добавили

        if intent in ESCALATION_INTENTS:
            await create_escalation(conversation_id, intent, text, chat_id=chat_id)
            reply = "Передал ваш вопрос специалисту, скоро ответим."

        elif intent in RAG_INTENTS:
            category = intent_to_category(intent)
            chunks = await retrieve(query=text, category=category)
            reply = await rag_answer(query=text, chunks=chunks, history=history)  # ← пробросили

        elif intent == "спам":
            reply = "Если у вас есть конкретный вопрос, сформулируйте его пожалуйста."

        else:
            reply = await handle_other_intent(text, history=history)  # ← пробросили

        await log_message(conversation_id, "assistant", reply)
        await send_message(chat_id, reply)

    except GroqRateLimitExhausted as e:
        if e.retry_after <= RETRY_AFTER_ESCALATION_THRESHOLD:
            logger.warning(f"Повторный rate-limit, ретрай через {e.retry_after}s")
            redis = ctx["redis"]
            await redis.enqueue_job(
                "retry_llm_pipeline",
                chat_id=chat_id,
                text=text,
                conversation_id=conversation_id,
                _defer_by=e.retry_after,
            )
        else:
            logger.warning(f"Rate-limit слишком долгий ({e.retry_after}s), эскалирую")
            await create_escalation(
                conversation_id,
                intent="другое",
                message_text=text,
                chat_id=chat_id,
                reason="llm_unavailable",
            )
            await send_message(
                chat_id,
                "Прошу прощения за ожидание — передал ваш вопрос специалисту.",
            )


async def mark_resolved(
    ctx,
    conversation_id: int,
    scheduled_at: float,  # unix timestamp момента постановки задачи
) -> None:
    """
    Переводит диалог в resolved если после постановки задачи
    не было новых сообщений.

    Логика вместо отмены ARQ задачи:
    ARQ не поддерживает отмену задач по ID. Вместо этого при срабатывании
    проверяем last_message_at — если оно позже scheduled_at, значит пришли
    новые сообщения и диалог трогать не нужно. main.py поставит новую
    mark_resolved задачу при следующем ответе.
    """
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_message_at, status FROM conversations WHERE id = $1",
            conversation_id,
        )

    if not row:
        logger.warning(f"[mark_resolved] conversation {conversation_id} не найден")
        return

    if row["status"] != "active":
        # Диалог уже escalated или resolved — не трогаем
        logger.info(f"[mark_resolved] conversation {conversation_id} статус={row['status']}, пропускаем")
        return

    last_message_ts = row["last_message_at"].timestamp()
    if last_message_ts > scheduled_at:
        # После постановки задачи пришли новые сообщения — не закрываем.
        # main.py при следующем ответе поставит новую задачу mark_resolved.
        logger.info(
            f"[mark_resolved] conversation {conversation_id}: "
            f"новые сообщения после scheduled_at, пропускаем"
        )
        return

    await update_conversation_status(conversation_id, "resolved")
    logger.info(f"[mark_resolved] conversation {conversation_id} → resolved")





    """
    Что происходит при изменении файла на Drive:

    1. Drive шлёт POST на /drive/webhook — пустое тело, только заголовки
    X-Goog-Resource-State может быть sync (первое уведомление при подписке, игнорируем) или change (реальное изменение)
    2. Webhook отвечает 200 немедленно — Drive ждёт не больше 10 секунд, иначе считает доставку неудачной
    3. ARQ job process_drive_changes идёт в changes.list с pageToken из Redis, обрабатывает каждое изменение
    """


async def process_drive_changes(ctx) -> None:
    """
    Забирает изменения из Drive API начиная с сохранённого pageToken,
    обрабатывает каждое: ingest или delete.
    """
    from rag.drive_client import list_changes
    from rag.drive_ingestion import ingest_drive_file, delete_drive_file
    from config import DRIVE_FOLDER_CATEGORY

    redis = ctx["redis"]
    page_token = await redis.get("drive:page_token")

    if not page_token:
        logger.warning("[process_drive_changes] нет pageToken в Redis, пропускаем")
        return

    changes, new_token = await list_changes(page_token)
    logger.info(f"[process_drive_changes] {len(changes)} изменений")

    for change in changes:
        file_info = change.get("file")
        file_id = change.get("fileId")

        # Файл удалён или перемещён в корзину
        if change.get("removed") or (file_info and file_info.get("trashed")):
            await delete_drive_file(file_id)
            continue

        if not file_info:
            continue

        # Определяем категорию по папке-родителю
        parents = file_info.get("parents", [])
        category = None
        for parent_id in parents:
            if parent_id in DRIVE_FOLDER_CATEGORY:
                category = DRIVE_FOLDER_CATEGORY[parent_id]
                break

        if not category:
            logger.info(f"[process_drive_changes] файл {file_id} не в отслеживаемой папке, пропускаем")
            continue

        await ingest_drive_file(
            file_id=file_id,
            filename=file_info["name"],
            mime_type=file_info["mimeType"],
            category=category,
            web_view_link=file_info.get("webViewLink"),
        )

    await redis.set("drive:page_token", new_token)

async def renew_drive_watch(ctx) -> None:
    import uuid
    from datetime import datetime, timezone, timedelta
    from rag.drive_client import watch_changes, stop_watch
    from db import get_changes_watch, upsert_changes_watch
    from config import settings

    existing = await get_changes_watch()
    if not existing:
        logger.warning("[renew_drive_watch] нет активной подписки")
        return

    # Обновляем если истекает в ближайшие 24 часа
    if existing["expires_at"] > datetime.now(tz=timezone.utc) + timedelta(hours=24):
        logger.info("[renew_drive_watch] подписка ещё свежая, пропускаем")
        return

    try:
        await stop_watch(existing["channel_id"], existing["resource_id"])
    except Exception as e:
        logger.warning(f"[renew_drive_watch] stop_watch failed: {e}")

    redis = ctx["redis"]
    page_token = await redis.get("drive:page_token")
    if not page_token:
        from rag.drive_client import get_start_page_token
        page_token = await get_start_page_token()
        await redis.set("drive:page_token", str(page_token))

    webhook_url = f"https://{settings.render_app_url}/drive/webhook?token={settings.google_webhook_secret}"
    channel_id = str(uuid.uuid4())

    response = await watch_changes(webhook_url, channel_id, page_token)
    expires_at = datetime.fromtimestamp(
        int(response["expiration"]) / 1000,
        tz=timezone.utc,
    )
    await upsert_changes_watch(
        channel_id=channel_id,
        resource_id=response["resourceId"],
        expires_at=expires_at,
    )
    logger.info(f"[renew_drive_watch] подписка обновлена, истекает {expires_at}")