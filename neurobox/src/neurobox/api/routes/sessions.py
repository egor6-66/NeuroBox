"""Сессии по HTTP — то, на что сядет пульт.

Формы ответов не повторяют таблицы: наружу едет то, что нужно читателю, а не то, как оно
хранится. Иначе любая правка схемы становится ломающей для всех потребителей.
"""

import json
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from neurobox.api.deps import CurrentCatalog, CurrentDb, CurrentRegistry
from neurobox.core.config import settings
from neurobox.db.engine import sessions as db_sessions
from neurobox.db.models import Author, RunState
from neurobox.sessions import service
from neurobox.sessions.runner import runner

router = APIRouter(prefix="/sessions", tags=["sessions"])


class NewSession(BaseModel):
    recipe: str
    passport: str
    agent: str
    title: str | None = None


class SessionOut(BaseModel):
    id: str
    title: str | None
    recipe: str
    passport: str
    agent: str
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    author: Author
    text: str
    run_id: str | None
    created_at: datetime


class RunOut(BaseModel):
    id: str
    state: RunState
    refusal: str | None = None
    means: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    cost_micros: int | None = None
    duration_ms: int | None = None
    created_at: datetime
    finished_at: datetime | None = None


class Accepted(BaseModel):
    """Реплика принята в работу. Ответа здесь нет — за ним идут в поток событий."""

    run: RunOut


def _out(session: object) -> SessionOut:
    return SessionOut.model_validate(session, from_attributes=True)


async def _mine(db: CurrentDb, session_id: str) -> object:
    session = await service.by_id(db, session_id, settings.owner_id)
    if session is None:
        # Чужая сессия и несуществующая отвечают одинаково: иначе по разнице ответов можно
        # перебором узнать, какие сессии вообще есть у других.
        raise HTTPException(status_code=404, detail=f"сессии {session_id!r} нет")
    return session


@router.post("", status_code=201)
async def create(body: NewSession, db: CurrentDb, catalog: CurrentCatalog) -> SessionOut:
    """Завести разговор. Названное проверяется сразу: сессия, ссылающаяся в пустоту, бесполезна."""
    for kind, name, known in (
        ("рецепта", body.recipe, catalog.recipes),
        ("паспорта", body.passport, catalog.passports),
        ("агента", body.agent, catalog.agents),
    ):
        if name not in known:
            raise HTTPException(status_code=400, detail=f"{kind} {name!r} нет в каталоге")

    session = await service.create(
        db,
        owner_id=settings.owner_id,
        recipe=body.recipe,
        passport=body.passport,
        agent=body.agent,
        title=body.title,
    )
    return _out(session)


@router.get("")
async def listing(db: CurrentDb) -> list[SessionOut]:
    return [_out(s) for s in await service.listing(db, settings.owner_id)]


@router.get("/{session_id}")
async def one(session_id: str, db: CurrentDb) -> SessionOut:
    return _out(await _mine(db, session_id))


@router.get("/{session_id}/messages")
async def messages(session_id: str, db: CurrentDb) -> list[MessageOut]:
    await _mine(db, session_id)
    found = await service.history(db, session_id)
    return [MessageOut.model_validate(m, from_attributes=True) for m in found]


@router.get("/{session_id}/runs")
async def runs(session_id: str, db: CurrentDb) -> list[RunOut]:
    await _mine(db, session_id)
    found = await service.runs_of(db, session_id)
    return [RunOut.model_validate(r, from_attributes=True) for r in found]


class Saying(BaseModel):
    text: str


@router.post("/{session_id}/messages", status_code=202)
async def say(
    session_id: str,
    body: Saying,
    db: CurrentDb,
    catalog: CurrentCatalog,
    registry: CurrentRegistry,
) -> Accepted:
    """Сказать агенту. Управление возвращается сразу, ответ приходит потоком событий.

    Держать соединение до конца прогона нельзя: агент думает минутами, а прокси, балансировщик и
    браузер закроют запрос раньше — и работа умрёт вместе с соединением.
    """
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="пустая реплика")

    session = await _mine(db, session_id)
    probes = {p.seed: p for p in registry.known()}

    try:
        run = await runner.start(db_sessions(), session, catalog, probes, body.text)  # type: ignore[arg-type]
    except service.Missing as missing:
        raise HTTPException(status_code=409, detail=missing.refusal.means) from missing

    return Accepted(run=RunOut.model_validate(run, from_attributes=True))


@router.get("/{session_id}/events")
async def events(session_id: str, request: Request, db: CurrentDb) -> EventSourceResponse:
    """Поток событий сессии.

    Клиент вправе отвалиться и вернуться: прогон от этого не прекращается, а состояние всегда
    можно дочитать из истории и списка прогонов.
    """
    await _mine(db, session_id)

    async def stream() -> AsyncIterator[dict[str, str]]:
        async for event in runner.watch(session_id):
            if await request.is_disconnected():
                break
            yield {"event": str(event.get("event", "message")),
                   "data": json.dumps(event, ensure_ascii=False)}

    return EventSourceResponse(stream())


@router.post("/{session_id}/runs/{run_id}/cancel")
async def cancel(session_id: str, run_id: str, db: CurrentDb) -> RunOut:
    """Прервать прогон.

    Отмена — явная операция, а не «клиент ушёл, значит хватит»: ушедший клиент может вернуться,
    а прерванная без спроса работа стоила денег зря.
    """
    await _mine(db, session_id)

    run = await service.run_by_id(db, run_id)
    if run is None or run.session_id != session_id:
        raise HTTPException(status_code=404, detail=f"прогона {run_id!r} нет в этой сессии")

    if run.state is not RunState.WORKING:
        raise HTTPException(
            status_code=409, detail=f"прогон уже завершён: {run.state.value}"
        )

    if not await runner.cancel(db_sessions(), run_id):
        # Задачи нет, а запись говорит «работает» — значит её исполнял умерший процесс.
        await service.cancelled(db, run, "прогон не исполнялся этим процессом")

    await db.refresh(run)
    return RunOut.model_validate(run, from_attributes=True)
