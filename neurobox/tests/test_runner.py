"""Фоновый прогон: не держит соединение, слушается потоком, прерывается и переживает рестарт."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from neurobox.a2a.client import Answer
from neurobox.db.models import Author, Base, Message, Run, RunState
from neurobox.model.refusal import RefusalName
from neurobox.sessions import service
from neurobox.sessions.runner import Runner, reconcile
from tests.test_sessions import AGENT_CALL, a_session, catalog_of

Maker = async_sessionmaker[AsyncSession]


@pytest_asyncio.fixture()
async def maker(tmp_path: Path) -> AsyncIterator[Maker]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'проба.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


ANSWERED = Answer(ok=True, text="готово", state="TASK_STATE_COMPLETED")


def slow_agent(monkeypatch: pytest.MonkeyPatch, seconds: float, answer: Answer = ANSWERED) -> None:
    async def slow(url: str, prompt: str, **kwargs: Any) -> Answer:  # noqa: ARG001
        await asyncio.sleep(seconds)
        return answer

    monkeypatch.setattr(AGENT_CALL, slow)


async def wait_until(check: Any, limit: float = 5.0) -> bool:
    """Дождаться условия, а не спать наугад: сон наугад делает тест то зелёным, то красным."""
    deadline = asyncio.get_running_loop().time() + limit
    while asyncio.get_running_loop().time() < deadline:
        if await check():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.mark.asyncio
async def test_reply_does_not_hold_the_caller(
    maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ручка обязана вернуться сразу: агент думает минутами, соединение столько не живёт."""
    slow_agent(monkeypatch, 0.4)
    runner = Runner()
    async with maker() as db:
        session = await a_session(db)

    started = asyncio.get_running_loop().time()
    run = await runner.start(maker, session, catalog_of(), {}, "вопрос")
    spent = asyncio.get_running_loop().time() - started

    assert spent < 0.2
    assert run.state is RunState.WORKING
    assert runner.working(run.id)


@pytest.mark.asyncio
async def test_run_finishes_in_the_background(
    maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow_agent(monkeypatch, 0.1)
    runner = Runner()
    async with maker() as db:
        session = await a_session(db)
    run = await runner.start(maker, session, catalog_of(), {}, "вопрос")

    async def done() -> bool:
        async with maker() as db:
            found = await service.run_by_id(db, run.id)
            return found is not None and found.state is RunState.COMPLETED

    assert await wait_until(done)

    async with maker() as db:
        history = await service.history(db, session.id)
    assert [(m.author, m.text) for m in history] == [
        (Author.HUMAN, "вопрос"),
        (Author.AGENT, "готово"),
    ]


@pytest.mark.asyncio
async def test_watchers_hear_start_and_finish(
    maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow_agent(monkeypatch, 0.05)
    runner = Runner()
    async with maker() as db:
        session = await a_session(db)

    heard: list[str] = []

    async def listen() -> None:
        async for event in runner.watch(session.id):
            heard.append(str(event["event"]))
            if event["event"] == "run-finished":
                return

    listening = asyncio.create_task(listen())
    await wait_until(lambda: asyncio.sleep(0, result=runner.listeners_of(session.id) > 0))
    await runner.start(maker, session, catalog_of(), {}, "вопрос")
    await asyncio.wait_for(listening, timeout=5)

    assert heard == ["run-started", "run-finished"]


@pytest.mark.asyncio
async def test_listener_unsubscribes_when_it_leaves() -> None:
    """Иначе очередь ушедшего клиента копила бы события навсегда."""
    runner = Runner()

    async def peek() -> None:
        async for _ in runner.watch("с"):
            return

    task = asyncio.create_task(peek())
    await wait_until(lambda: asyncio.sleep(0, result=runner.listeners_of("с") > 0))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert runner.listeners_of("с") == 0


# --- отмена ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_stops_the_run_and_marks_it(
    maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow_agent(monkeypatch, 30)
    runner = Runner()
    async with maker() as db:
        session = await a_session(db)
    run = await runner.start(maker, session, catalog_of(), {}, "вопрос")

    assert await runner.cancel(maker, run.id)

    async with maker() as db:
        found = await service.run_by_id(db, run.id)
    assert found is not None
    assert found.state is RunState.CANCELED
    assert found.refusal == RefusalName.CANCELED.value
    assert found.finished_at is not None


@pytest.mark.asyncio
async def test_cancelling_a_finished_run_changes_nothing(
    maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    slow_agent(monkeypatch, 0.05)
    runner = Runner()
    async with maker() as db:
        session = await a_session(db)
    run = await runner.start(maker, session, catalog_of(), {}, "вопрос")

    async def done() -> bool:
        async with maker() as db:
            found = await service.run_by_id(db, run.id)
            return found is not None and found.state is RunState.COMPLETED

    assert await wait_until(done)
    assert await runner.cancel(maker, run.id) is False

    async with maker() as db:
        found = await service.run_by_id(db, run.id)
    assert found is not None and found.state is RunState.COMPLETED


@pytest.mark.asyncio
async def test_cancelled_run_leaves_no_agent_reply(
    maker: Maker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Прерванный прогон не должен дописывать ответ, которого человек уже не ждёт."""
    slow_agent(monkeypatch, 30)
    runner = Runner()
    async with maker() as db:
        session = await a_session(db)
    run = await runner.start(maker, session, catalog_of(), {}, "вопрос")
    await runner.cancel(maker, run.id)

    async with maker() as db:
        found = await db.execute(select(Message).where(Message.author == Author.AGENT))
    assert found.scalars().all() == []


# --- рестарт ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_closes_orphaned_runs(maker: Maker) -> None:
    """Прогон в «работает» после старта означает мёртвый процесс: продолжить его некому."""
    async with maker() as db:
        session = await a_session(db)
        db.add(Run(id="брошенный", session_id=session.id, state=RunState.WORKING))
        await db.commit()

    closed = await reconcile(maker)

    assert closed == 1
    async with maker() as db:
        found = await service.run_by_id(db, "брошенный")
    assert found is not None
    assert found.state is RunState.FAILED
    assert found.refusal == RefusalName.INTERRUPTED.value


@pytest.mark.asyncio
async def test_restart_leaves_finished_runs_alone(maker: Maker) -> None:
    async with maker() as db:
        session = await a_session(db)
        db.add(Run(id="доделанный", session_id=session.id, state=RunState.COMPLETED))
        await db.commit()

    assert await reconcile(maker) == 0
