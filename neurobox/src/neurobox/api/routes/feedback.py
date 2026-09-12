"""Отзывы о самом боксе: от человека и от агента.

Единственное, что бокс хранит по существу. Разговоры принадлежат тому, кто их ведёт, и уезжают
обратно; а вот жалобы и похвалы на НАШУ работу — наши, и собирать их больше некому.

Про чужие зоны сюда не пишут. У каждой свои ручки отзывов, и затык с их ручками нужен там, где
живёт сама зона: у нас он превратился бы в запись о том, чего мы не чиним и что сменится раньше,
чем мы её прочтём.

Знак обоих родов. По одним жалобам не видно, что работает, и разбор превращается в список
претензий — а при переделке важнее знать, что НЕ трогать.
"""

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from neurobox.api.deps import CurrentDb
from neurobox.api.identity import Caller
from neurobox.db.models import Note, NoteKind, Session
from neurobox.sessions import service

router = APIRouter(prefix="/feedback", tags=["feedback"])


class Said(BaseModel):
    """Отзыв от человека. Форму диктуем мы — это про нашу работу."""

    kind: NoteKind = NoteKind.FRICTION
    what: str = Field(min_length=1)
    where: str | None = None
    workaround: str | None = None


class Entry(BaseModel):
    thread: str
    kind: NoteKind
    what: str
    where: str | None
    workaround: str | None
    created_at: datetime


@router.post("/{thread_id}", status_code=201)
async def report(thread_id: str, body: Said, caller: Caller, db: CurrentDb) -> Entry:
    """Записать отзыв человека о работе бокса.

    Привязан к потоку, а не висит сам по себе: «мешало вот здесь» без места разбирать нечем, а
    поток — единственное место, которое мы про этот разговор помним.
    """
    session = await service.by_id(db, thread_id, caller.owner_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"потока {thread_id!r} нет")

    note = Note(
        session_id=thread_id,
        kind=body.kind,
        what=body.what.strip(),
        where=(body.where or "").strip() or None,
        workaround=(body.workaround or "").strip() or None,
    )
    db.add(note)
    await db.commit()

    return Entry(
        thread=thread_id,
        kind=note.kind,
        what=note.what,
        where=note.where,
        workaround=note.workaround,
        created_at=note.created_at,
    )


@router.get("")
async def listing(caller: Caller, db: CurrentDb, limit: int = 100) -> list[Entry]:
    """Что накопилось по потокам этого владельца. Свежее сверху — чинят обычно последнее.

    Чужих отзывов не отдаём: они привязаны к потокам, а поток принадлежит одному человеку.
    """
    found = await db.execute(
        select(Note)
        .join(Session, Session.id == Note.session_id)
        .where(Session.owner_id == caller.owner_id)
        .order_by(Note.created_at.desc())
        .limit(limit)
    )

    return [
        Entry(
            thread=note.session_id,
            kind=note.kind,
            what=note.what,
            where=note.where,
            workaround=note.workaround,
            created_at=note.created_at,
        )
        for note in found.scalars()
    ]
