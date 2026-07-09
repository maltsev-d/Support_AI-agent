# worker/settings.py
from arq.connections import RedisSettings
from config import settings
from worker.tasks import retry_llm_pipeline


class WorkerSettings:
    functions = [retry_llm_pipeline]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)