"""Живость и готовность — два разных вопроса, поэтому две разные ручки.

`/health` отвечает «процесс поднялся и обрабатывает запросы». `/ready` отвечает «я могу
работать»: база отвечает. Разница не формальная — контейнер, здоровый по первому вопросу и
неготовый по второму, получит трафик и будет отказывать на каждом запросе.
"""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from neurobox.db.engine import sessions

router = APIRouter(tags=["meta"])


class Readiness(BaseModel):
    ready: bool
    database: bool
    means: str | None = None
    """Что именно не так, если не готов. Пустая ручка готовности заставляет лезть в логи."""


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(response: Response) -> Readiness:
    try:
        async with sessions()() as db:
            await db.execute(text("select 1"))
    except (SQLAlchemyError, OSError) as error:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Readiness(
            ready=False,
            database=False,
            means=f"база не отвечает: {type(error).__name__}: {error}".strip()[:300],
        )

    return Readiness(ready=True, database=True)
