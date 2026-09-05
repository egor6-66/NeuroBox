"""Точка входа приложения."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from neurobox.api.main import api_router
from neurobox.core.config import settings
from neurobox.db.engine import dispose, sessions
from neurobox.sessions.runner import reconcile


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """Прогоны, оборванные прошлым запуском, закрываются при старте.

    Иначе они остаются в состоянии «работает» навсегда: исполнявший их процесс мёртв, продолжить
    их некому, и человек видел бы вечно думающего агента.
    """
    await reconcile(sessions())
    yield
    await dispose()


app = FastAPI(title=settings.project_name, lifespan=lifespan)

app.include_router(api_router)
