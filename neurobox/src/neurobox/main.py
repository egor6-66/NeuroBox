"""Точка входа приложения."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError

from neurobox.api.access import Access
from neurobox.api.main import api_router
from neurobox.core import logs
from neurobox.core.config import settings
from neurobox.db.engine import dispose, sessions
from neurobox.sessions.runner import reconcile

log = logging.getLogger("neurobox")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """Прогоны, оборванные прошлым запуском, закрываются при старте.

    Иначе они остаются в состоянии «работает» навсегда: исполнявший их процесс мёртв, продолжить
    их некому, и человек видел бы вечно думающего агента.
    """
    logs.setup()

    # Недоступная база НЕ мешает сервису подняться: он обязан ответить на вопрос о готовности
    # словами, а не умереть без объяснений. Иначе человек видит упавший контейнер и не знает,
    # сломан сервис или просто не поднялась база.
    closed: int | None = None
    try:
        closed = await reconcile(sessions())
    except (SQLAlchemyError, OSError) as error:
        log.warning(
            "база недоступна при старте, оборванные прогоны не закрыты",
            extra={"means": f"{type(error).__name__}: {error}"[:300]},
        )

    log.info("сервис поднят", extra={"closed_runs": closed, "environment": settings.environment})
    yield
    await dispose()


app = FastAPI(title=settings.project_name, lifespan=lifespan)

app.add_middleware(Access)
app.include_router(api_router)
