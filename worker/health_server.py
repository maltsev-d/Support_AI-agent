# worker/health_server.py
# Render Web Service требует открытый HTTP-порт, а arq worker сам по себе
# порт не слушает — он просто крутит цикл опроса Redis. Поднимаем рядом
# игрушечный FastAPI на /health в ТОМ ЖЕ event loop, чтобы Render
# не считал сервис упавшим (без открытого порта Render убьёт процесс).
import asyncio
import os
from fastapi import FastAPI
import uvicorn
from arq.worker import Worker
from worker.settings import WorkerSettings
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}

@app.head("/health")
async def health():
    return {"status": "ok"}


async def main():
    port = int(os.getenv("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)

    # handle_signals=False обязателен: ARQ по умолчанию сам вешает обработчики
    # SIGINT/SIGTERM на event loop и глушит их для себя — конфликтует с тем,
    # что uvicorn в том же процессе тоже должен на них реагировать и штатно
    # завершаться (см. arq issue #182 про запуск внутри FastAPI).
    arq_worker = Worker(
        functions=WorkerSettings.functions,
        redis_settings=WorkerSettings.redis_settings,
        on_startup=WorkerSettings.on_startup,
        on_shutdown=WorkerSettings.on_shutdown,
        handle_signals=False,
    )

    # async_run() — корутина, живёт в этом же event loop, никакого
    # отдельного треда/процесса не нужно
    await asyncio.gather(
        server.serve(),
        arq_worker.async_run(),
    )


if __name__ == "__main__":
    asyncio.run(main())