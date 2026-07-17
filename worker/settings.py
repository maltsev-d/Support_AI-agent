# worker/settings.py
from arq.connections import RedisSettings
from config import settings
from worker.tasks import retry_llm_pipeline, mark_resolved, process_drive_changes
import db


async def on_startup(ctx):
    """
    Вызывается ARQ один раз при старте воркера.
    Инициализируем пул БД — без этого db.pool = None
    и любой вызов pool.acquire() в tasks.py упадёт.
    """
    await db.init_pool()


async def on_shutdown(ctx):
    """Закрываем пул при остановке — не держим лишние соединения."""
    await db.close_pool()


class WorkerSettings:
    functions = [retry_llm_pipeline, mark_resolved, process_drive_changes]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = on_startup
    on_shutdown = on_shutdown
