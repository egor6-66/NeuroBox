"""Вход по протоколу: что бокс принимает и какими событиями отвечает.

Проверяется КОНТРАКТ, а не внутренности: конверт на входе, последовательность событий на выходе.
Внутри может стоять любой рантайм — протокол от этого не меняется, в этом и весь смысл.
"""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from neurobox.a2a.client import Answer
from neurobox.a2a.stream import Step
from neurobox.api.deps import get_catalog
from neurobox.api.identity import LOGIN_HEADER
from neurobox.core.config import settings
from neurobox.db import engine as db_engine
from neurobox.db.models import Base
from neurobox.main import app
from neurobox.model.catalog import merge
from neurobox.model.entities import Agent as AgentEntity
from neurobox.model.entities import KnowledgeSeed, Layer, Passport, Recipe
from neurobox.model.files import LayerContents
from neurobox.model.refusal import Refusal, RefusalName


def catalog_of() -> Any:
    contents = LayerContents(Layer.FILE)
    contents.seeds["правила"] = KnowledgeSeed(name="правила", layer=Layer.FILE, text="как жить")
    contents.recipes["р"] = Recipe(name="р", layer=Layer.FILE, seeds=["правила"])
    contents.passports["п"] = Passport(
        name="п", layer=Layer.FILE, provider="claude-code", model="opus"
    )
    contents.agents["а"] = AgentEntity(name="а", layer=Layer.FILE, url="http://agent/")
    return merge([contents])


def envelope(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "threadId": "поток-1",
        "runId": "прогон-1",
        "messages": [{"id": "m1", "role": "user", "content": "сделай кнопку"}],
        "tools": [],
        "context": [],
        "forwardedProps": {"recipe": "р", "passport": "п", "agent": "а"},
    }
    body.update(over)
    return body


def agent_says(
    monkeypatch: pytest.MonkeyPatch, *, steps: list[Step], answer: Answer
) -> None:
    """Подменить рантайм: он отдаёт заданные шаги и заданный итог."""

    async def stream(url: str, prompt: str, **kwargs: Any) -> AsyncIterator[Step | Answer]:  # noqa: ARG001
        for step in steps:
            yield step
        yield answer

    # Подменяется и модуль, и ссылка на него в прогоне: прогон держит `stream` у себя, и правка
    # только исходного модуля до него не доезжает.
    monkeypatch.setattr("neurobox.a2a.stream.send", stream)
    monkeypatch.setattr("neurobox.sessions.runner.stream.send", stream)


@pytest.fixture()
def client(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'проба.sqlite'}")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def prepared() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    import asyncio

    asyncio.run(prepared())

    monkeypatch.setattr(db_engine, "sessions", lambda: maker)
    monkeypatch.setattr("neurobox.api.routes.agent.db_sessions", lambda: maker)
    monkeypatch.setattr(settings, "environment", "local")
    monkeypatch.setattr(settings, "access_token", "")

    app.dependency_overrides[get_catalog] = catalog_of
    yield TestClient(app)
    app.dependency_overrides.clear()


def frames(response: Any) -> list[dict[str, Any]]:
    """Разобрать поток в список событий. Тип лежит ВНУТРИ данных — так велит протокол."""
    out: list[dict[str, Any]] = []
    for line in response.text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


# Логин ЛАТИНИЦЕЙ: он ездит в заголовке HTTP, а туда кириллица не проходит вовсе.
HEADERS = {LOGIN_HEADER: "chelovek"}


def test_envelope_without_a_human_reply_is_refused(client: TestClient) -> None:
    """Прогон без реплики — работа без задачи. Молча принять её значило бы списать деньги ни за что."""
    answer = client.post("/agent", json=envelope(messages=[]), headers=HEADERS)

    assert answer.status_code == 422


def test_unknown_recipe_is_named(client: TestClient) -> None:
    """Имя, которого нет в каталоге, отбивается словами: иначе агент уходит работать без ручек."""
    answer = client.post(
        "/agent",
        json=envelope(forwardedProps={"recipe": "нет-такого"}),
        headers=HEADERS,
    )

    assert answer.status_code == 400
    assert "нет-такого" in answer.json()["detail"]


def test_run_streams_the_protocol_in_order(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Порядок событий и есть контракт: по нему клиент рисует ход работы."""
    agent_says(
        monkeypatch,
        steps=[
            Step(kind="using", text="зовёт", tool="mcp__skin__save_content", arguments={"a": 1}),
            Step(kind="result", text="сохранено", tool_call_id="вызов-1"),
        ],
        answer=Answer(ok=True, text="готово", state="TASK_STATE_COMPLETED"),
    )

    with client.stream("POST", "/agent", json=envelope(), headers=HEADERS) as answer:
        answer.read()
        seen = [f["type"] for f in frames(answer)]

    assert seen == [
        "RUN_STARTED",
        "TOOL_CALL_START",
        "TOOL_CALL_ARGS",
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]


def test_tool_result_carries_the_call_it_answers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Идентификатор вызова приходит от рантайма и уезжает как есть.

    В одном ходу вызовов бывает несколько, и подмени мы его своей нумерацией — снаружи результат
    не приписать к своей просьбе.
    """
    agent_says(
        monkeypatch,
        steps=[Step(kind="result", text="сохранено", tool_call_id="вызов-7", failed=False)],
        answer=Answer(ok=True, text="готово", state="TASK_STATE_COMPLETED"),
    )

    with client.stream("POST", "/agent", json=envelope(), headers=HEADERS) as answer:
        answer.read()
        result = next(f for f in frames(answer) if f["type"] == "TOOL_CALL_RESULT")

    assert result["toolCallId"] == "вызов-7"
    assert result["content"] == "сохранено"


def test_refusal_arrives_named(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """«Что-то пошло не так» нельзя ни показать человеку, ни обработать клиенту."""
    agent_says(
        monkeypatch,
        steps=[],
        answer=Answer(
            ok=False,
            text="",
            state="TASK_STATE_FAILED",
            refusals=[Refusal(name=RefusalName.SERVER_SILENT, means="сервер не ответил")],
        ),
    )

    with client.stream("POST", "/agent", json=envelope(), headers=HEADERS) as answer:
        answer.read()
        last = frames(answer)[-1]

    assert last["type"] == "RUN_ERROR"
    assert last["code"] == RefusalName.SERVER_SILENT.value
    assert last["message"] == "сервер не ответил"


def test_someone_elses_thread_is_not_picked_up(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Имя потока придумывает потребитель, и совпадение имён у двух людей — вопрос времени."""
    agent_says(
        monkeypatch,
        steps=[],
        answer=Answer(ok=True, text="готово", state="TASK_STATE_COMPLETED"),
    )

    with client.stream("POST", "/agent", json=envelope(), headers=HEADERS) as first:
        first.read()

    answer = client.post("/agent", json=envelope(), headers={LOGIN_HEADER: "drugoy"})

    assert answer.status_code == 409
