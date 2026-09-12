"""Хранилище: что переживает рестарт и что при этом обязано быть правдой."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from neurobox.db.models import Base, Note, NoteKind, Run, RunState, Session


@pytest_asyncio.fixture()
async def db(tmp_path) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    # Своя база на файл в каждом тесте: общая в памяти протекала бы состоянием между ними.
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'проба.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def a_session(sid: str = "с-1", owner: str = "local") -> Session:
    return Session(id=sid, owner_id=owner, recipe="р", passport="п", agent="а")


@pytest.mark.asyncio
async def test_owner_is_required(db: AsyncSession) -> None:
    """Владелец не необязательное поле: сессия без него потом никому не приписывается честно."""
    db.add(Session(id="с-2", recipe="р", passport="п", agent="а"))

    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_run_keeps_what_it_was_fed(db: AsyncSession) -> None:
    """Развёртка запоминается вместе с прогоном: рецепт назавтра другой, а разбор нужен по тому,
    что было на момент запуска."""
    session = a_session("с-3")
    session.runs.append(
        Run(
            id="з-3",
            state=RunState.COMPLETED,
            unfolded={"instructions": "правила", "servers": ["windshift"]},
            prompt_tokens=120,
            completion_tokens=30,
            finished_at=datetime.now(UTC),
        )
    )
    db.add(session)
    await db.commit()

    run = (await db.execute(select(Run).where(Run.id == "з-3"))).scalar_one()

    assert run.unfolded["servers"] == ["windshift"]
    assert run.prompt_tokens == 120


@pytest.mark.asyncio
async def test_unmeasured_cost_stays_empty_not_zero(db: AsyncSession) -> None:
    """Ноль означал бы «бесплатно», а правда — «провайдер не сказал»."""
    session = a_session("с-4")
    session.runs.append(Run(id="з-4", state=RunState.WORKING))
    db.add(session)
    await db.commit()

    run = (await db.execute(select(Run).where(Run.id == "з-4"))).scalar_one()

    assert run.prompt_tokens is None
    assert run.cost_micros is None


@pytest.mark.asyncio
async def test_failed_run_carries_named_refusal(db: AsyncSession) -> None:
    session = a_session("с-5")
    session.runs.append(
        Run(id="з-5", state=RunState.FAILED, refusal="server-silent", means="агент не ответил")
    )
    db.add(session)
    await db.commit()

    run = (await db.execute(select(Run).where(Run.id == "з-5"))).scalar_one()

    assert run.state is RunState.FAILED
    assert run.refusal == "server-silent"


@pytest.mark.asyncio
async def test_enums_come_back_as_enums_not_strings(db: AsyncSession) -> None:
    """Аннотация `Mapped[RunState]` обязана быть правдой ПОСЛЕ чтения из базы.

    Пока колонка была простой строкой, из базы приходил `str`: сравнение по тождеству молча
    давало ложь, проверка типов этого не видела, а ответ ручки уезжал пустым.
    """
    session = a_session("с-7")
    session.runs.append(Run(id="з-7", state=RunState.COMPLETED))
    db.add(session)
    await db.commit()
    db.expunge_all()

    run = (await db.execute(select(Run))).scalar_one()

    assert run.state is RunState.COMPLETED


@pytest.mark.asyncio
async def test_slot_keeps_only_the_last_exchange(db: AsyncSession) -> None:
    """Истории у бокса нет — есть слот, который перезаписывается.

    Копия чужой переписки на наших дисках была бы обязанностью, которой нас не просили: разговор
    принадлежит тому, кто его ведёт, и приезжает к нам целиком на каждый прогон.
    """
    session = a_session("с-9")
    session.last_input, session.last_output = "первый вопрос", "первый ответ"
    db.add(session)
    await db.commit()

    session.last_input, session.last_output = "второй вопрос", "второй ответ"
    await db.commit()
    db.expunge_all()

    found = (await db.execute(select(Session).where(Session.id == "с-9"))).scalar_one()

    assert (found.last_input, found.last_output) == ("второй вопрос", "второй ответ")


@pytest.mark.asyncio
async def test_praise_is_stored_alongside_friction(db: AsyncSession) -> None:
    """Отзыв бывает обоих знаков, и оба доезжают до базы.

    По одним затыкам не видно, что работает: разбор превращается в список жалоб, и чинить
    начинают то, что и так в порядке.
    """
    db.add(a_session("с-8"))
    db.add(Note(session_id="с-8", kind=NoteKind.FRICTION, what="рецепт не дал ручки"))
    db.add(Note(session_id="с-8", kind=NoteKind.PRAISE, what="палитра собралась с первого раза"))
    await db.commit()
    db.expunge_all()

    stored = (await db.execute(select(Note).order_by(Note.id))).scalars().all()

    assert [n.kind for n in stored] == [NoteKind.FRICTION, NoteKind.PRAISE]

