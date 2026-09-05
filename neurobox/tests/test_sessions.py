"""Сессии и прогоны. Агент подменён: проверяется наша сторона, а не чужой сервис."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from neurobox.a2a.client import Answer, Usage
from neurobox.db.models import Author, Base, Message, Run, RunState, Session
from neurobox.model.catalog import merge
from neurobox.model.entities import Agent as AgentEntity
from neurobox.model.entities import KnowledgeSeed, Layer, Passport, Recipe
from neurobox.model.files import LayerContents
from neurobox.model.refusal import Refusal, RefusalName
from neurobox.sessions import service


@pytest_asyncio.fixture()
async def db(tmp_path: Path) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'проба.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def catalog_of(*, agent_url: str = "http://агент") -> Any:
    contents = LayerContents(Layer.FILE)
    contents.seeds["дока"] = KnowledgeSeed(name="дока", layer=Layer.FILE, text="прав код")
    contents.recipes["р"] = Recipe(name="р", layer=Layer.FILE, seeds=["дока"])
    contents.passports["п"] = Passport(
        name="п", layer=Layer.FILE, provider="claude-code", model="m", context=200000
    )
    contents.agents["а"] = AgentEntity(name="а", layer=Layer.FILE, url=agent_url)
    return merge([contents])


async def a_session(db: AsyncSession, owner: str = "local") -> Session:
    return await service.create(
        db, owner_id=owner, recipe="р", passport="п", agent="а", title=None
    )


class Spy:
    """Подменённый агент: запоминает, что ему прислали, и отвечает заданным."""

    def __init__(self, answer: Answer) -> None:
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    async def send(self, url: str, prompt: str, **kwargs: Any) -> Answer:
        self.calls.append({"url": url, "prompt": prompt, **kwargs})
        return self.answer


AGENT_CALL = "neurobox.a2a.client.send"
AGENT_STREAM = "neurobox.a2a.stream.send"


def spy_on(monkeypatch: pytest.MonkeyPatch, answer: Answer) -> Spy:
    spy = Spy(answer)
    monkeypatch.setattr(AGENT_CALL, spy.send)
    return spy


ANSWERED = Answer(ok=True, text="прав код", state="TASK_STATE_COMPLETED")


# --- удачный прогон --------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_lands_in_history(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    spy_on(monkeypatch, ANSWERED)
    session = await a_session(db)

    run = await service.say(db, session, catalog_of(), {}, "вопрос")

    assert run.state is RunState.COMPLETED
    history = await service.history(db, session.id)
    assert [(m.author, m.text) for m in history] == [
        (Author.HUMAN, "вопрос"),
        (Author.AGENT, "прав код"),
    ]


@pytest.mark.asyncio
async def test_agent_gets_the_unfolded_recipe(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Инструкция едет агенту, а не остаётся у нас: иначе рецепт ни на что не влияет."""
    spy = spy_on(monkeypatch, ANSWERED)
    session = await a_session(db)

    await service.say(db, session, catalog_of(), {}, "вопрос")

    metadata = spy.calls[0]["metadata"]
    assert "прав код" in metadata["systemPrompt"]
    assert spy.calls[0]["context_id"] == session.id


@pytest.mark.asyncio
async def test_run_remembers_what_it_was_fed(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy_on(monkeypatch, ANSWERED)
    session = await a_session(db)

    run = await service.say(db, session, catalog_of(), {}, "вопрос")

    assert "прав код" in run.unfolded["instructions"]


# --- продолжение беседы ----------------------------------------------------


@pytest.mark.asyncio
async def test_context_is_passed_but_continuation_is_not_our_call(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Мы даём агенту контекст и молчим о том, продолжать ли беседу.

    Пробовали решать за него по своей базе — ошибались: отменённый прогон беседу уже завёл, а по
    нашим записям она выглядела несостоявшейся, и следующий запуск падал на занятом имени. Знать
    это может только тот, кто беседу заводил.
    """
    spy = spy_on(monkeypatch, ANSWERED)
    session = await a_session(db)

    await service.say(db, session, catalog_of(), {}, "раз")
    await service.say(db, session, catalog_of(), {}, "два")

    assert [c["context_id"] for c in spy.calls] == [session.id, session.id]
    assert all("resume" not in c["metadata"] for c in spy.calls)


# --- отказы ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_run_keeps_named_refusal(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy_on(
        monkeypatch,
        Answer(
            ok=False,
            text="не хватило прав",
            refusals=[Refusal(name=RefusalName.RUN_FAILED, means="агент завершил отказом")],
        ),
    )
    session = await a_session(db)

    run = await service.say(db, session, catalog_of(), {}, "вопрос")

    assert run.state is RunState.FAILED
    assert run.refusal == RefusalName.RUN_FAILED.value
    # Текст отказа тоже попадает в историю: агент часто объясняет причину именно там.
    history = await service.history(db, session.id)
    assert history[-1].text == "не хватило прав"


@pytest.mark.asyncio
async def test_run_is_recorded_before_the_agent_is_called(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Упавший посреди разговора сервис обязан оставить след, а не тишину."""
    seen: dict[str, Any] = {}

    async def peek(url: str, prompt: str, **kwargs: Any) -> Answer:  # noqa: ARG001
        found = await db.execute(select(Run))
        seen["state"] = found.scalars().one().state
        return ANSWERED

    monkeypatch.setattr(AGENT_CALL, peek)
    session = await a_session(db)

    await service.say(db, session, catalog_of(), {}, "вопрос")

    assert seen["state"] is RunState.WORKING


@pytest.mark.asyncio
async def test_missing_recipe_is_our_side_not_the_agents(db: AsyncSession) -> None:
    session = await a_session(db)
    session.recipe = "нет-такого"

    with pytest.raises(service.Missing) as raised:
        await service.say(db, session, catalog_of(), {}, "вопрос")

    assert raised.value.refusal.name is RefusalName.SEED_UNKNOWN


# --- владелец --------------------------------------------------------------


@pytest.mark.asyncio
async def test_someone_elses_session_is_not_found(db: AsyncSession) -> None:
    """Отличать «чужая» от «нет такой» нельзя: по разнице ответов перебором узнаются чужие."""
    session = await a_session(db, owner="хозяин")

    assert await service.by_id(db, session.id, "чужой") is None
    assert await service.by_id(db, session.id, "хозяин") is not None


@pytest.mark.asyncio
async def test_listing_shows_freshest_first(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy_on(monkeypatch, ANSWERED)
    first = await a_session(db)
    second = await a_session(db)
    await service.say(db, first, catalog_of(), {}, "поговорили в первой")

    listing = await service.listing(db, "local")

    assert [s.id for s in listing] == [first.id, second.id]


@pytest.mark.asyncio
async def test_deleting_session_takes_runs_and_messages(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    spy_on(monkeypatch, ANSWERED)
    session = await a_session(db)
    await service.say(db, session, catalog_of(), {}, "вопрос")

    await db.delete(session)
    await db.commit()

    assert (await db.execute(select(Message))).scalars().all() == []
    assert (await db.execute(select(Run))).scalars().all() == []


# --- учёт расхода ----------------------------------------------------------


COSTED = Answer(
    ok=True,
    text="ответ",
    usage=Usage(
        input_tokens=2,
        output_tokens=4,
        cache_creation_tokens=3397,
        cache_read_tokens=12789,
        cost_usd=0.0404745,
        duration_ms=2873,
    ),
)


@pytest.mark.asyncio
async def test_usage_is_recorded_with_the_run(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Цифру называет агент в своём ответе — другого места, где она есть, не существует."""
    spy_on(monkeypatch, COSTED)
    session = await a_session(db)

    run = await service.say(db, session, catalog_of(), {}, "вопрос")

    assert run.prompt_tokens == 2
    assert run.completion_tokens == 4
    assert run.cache_creation_tokens == 3397
    assert run.cache_read_tokens == 12789
    assert run.duration_ms == 2873


@pytest.mark.asyncio
async def test_cost_is_stored_as_whole_micros(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Деньги целым числом: дробные типы копят ошибку, а миллионная доля цента не важна."""
    spy_on(monkeypatch, COSTED)
    session = await a_session(db)

    run = await service.say(db, session, catalog_of(), {}, "вопрос")

    assert run.cost_micros == 40474


@pytest.mark.asyncio
async def test_failed_run_still_costs(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Неудачная попытка тоже потратила деньги — квота, которая её не видит, врёт."""
    spy_on(
        monkeypatch,
        Answer(
            ok=False,
            text="не вышло",
            usage=Usage(input_tokens=5, output_tokens=1, cost_usd=0.002),
            refusals=[Refusal(name=RefusalName.RUN_FAILED, means="отказ")],
        ),
    )
    session = await a_session(db)

    run = await service.say(db, session, catalog_of(), {}, "вопрос")

    assert run.state is RunState.FAILED
    assert run.prompt_tokens == 5
    assert run.cost_micros == 2000


@pytest.mark.asyncio
async def test_unreported_usage_stays_empty(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Бесплатно» и «не сказали» — разные вещи, и путать их нельзя."""
    spy_on(monkeypatch, ANSWERED)
    session = await a_session(db)

    run = await service.say(db, session, catalog_of(), {}, "вопрос")

    assert run.prompt_tokens is None
    assert run.cost_micros is None
