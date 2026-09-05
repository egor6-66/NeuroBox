"""Сессии по HTTP — то, на что сядет пульт.

Формы ответов не повторяют таблицы: наружу едет то, что нужно читателю, а не то, как оно
хранится. Иначе любая правка схемы становится ломающей для всех потребителей.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from neurobox.api.deps import CurrentCatalog, CurrentDb, CurrentRegistry
from neurobox.core.config import settings
from neurobox.db.models import Author, RunState
from neurobox.sessions import service

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


class Said(BaseModel):
    """Ответ на реплику: сам прогон и то, что сказал агент."""

    run: RunOut
    reply: str = ""
    refusals: list[str] = Field(default_factory=list)


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


@router.post("/{session_id}/messages")
async def say(
    session_id: str,
    body: Saying,
    db: CurrentDb,
    catalog: CurrentCatalog,
    registry: CurrentRegistry,
) -> Said:
    """Сказать агенту и дождаться ответа.

    Пока синхронно: воркер и поток событий приезжают следующей фазой. Отказ агента при этом НЕ
    превращается в ошибку HTTP — прогон состоялся и записан, просто кончился отказом, и человек
    обязан увидеть причину, а не пятисотую страницу.
    """
    if not body.text.strip():
        raise HTTPException(status_code=422, detail="пустая реплика")

    session = await _mine(db, session_id)
    probes = {p.seed: p for p in registry.known()}

    try:
        run = await service.say(db, session, catalog, probes, body.text)  # type: ignore[arg-type]
    except service.Missing as missing:
        raise HTTPException(status_code=409, detail=missing.refusal.means) from missing

    reply = ""
    found = await service.history(db, session_id)
    if found and found[-1].author is Author.AGENT and found[-1].run_id == run.id:
        reply = found[-1].text

    return Said(
        run=RunOut.model_validate(run, from_attributes=True),
        reply=reply,
        refusals=[run.refusal] if run.refusal else [],
    )
