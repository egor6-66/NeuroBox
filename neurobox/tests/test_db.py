"""Хранилище: что переживает рестарт и что при этом обязано быть правдой."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from neurobox.db.models import Author, Base, Message, Run, RunState, Session


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
async def test_session_survives_with_its_history(db: AsyncSession) -> None:
    session = a_session()
    session.messages.append(Message(author=Author.HUMAN, text="привет"))
    session.messages.append(Message(author=Author.AGENT, text="здравствуй", run_id="з-1"))
    db.add(session)
    await db.commit()

    found = (await db.execute(select(Session).where(Session.id == "с-1"))).scalar_one()

    assert [m.author for m in found.messages] == [Author.HUMAN, Author.AGENT]
    assert found.messages[1].run_id == "з-1"


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
async def test_deleting_session_takes_its_history(db: AsyncSession) -> None:
    """Осиротевшие сообщения и прогоны — мусор, о котором никто не вспомнит."""
    session = a_session("с-6")
    session.messages.append(Message(author=Author.HUMAN, text="раз"))
    session.runs.append(Run(id="з-6", state=RunState.COMPLETED))
    db.add(session)
    await db.commit()

    await db.delete(session)
    await db.commit()

    assert (await db.execute(select(Message))).scalars().all() == []
    assert (await db.execute(select(Run))).scalars().all() == []


@pytest.mark.asyncio
async def test_enums_come_back_as_enums_not_strings(db: AsyncSession) -> None:
    """Аннотация `Mapped[Author]` обязана быть правдой ПОСЛЕ чтения из базы.

    Пока колонка была простой строкой, из базы приходил `str`: сравнение по тождеству молча
    давало ложь, проверка типов этого не видела, а ответ ручки уезжал пустым.
    """
    session = a_session("с-7")
    session.messages.append(Message(author=Author.AGENT, text="ответ", run_id="з-7"))
    session.runs.append(Run(id="з-7", state=RunState.COMPLETED))
    db.add(session)
    await db.commit()
    db.expunge_all()

    message = (await db.execute(select(Message))).scalar_one()
    run = (await db.execute(select(Run))).scalar_one()

    assert message.author is Author.AGENT
    assert run.state is RunState.COMPLETED
