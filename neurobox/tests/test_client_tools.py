"""Ручки приложения: бокс передаёт вызов и ждёт, но не исполняет.

Проверяется ГРАНИЦА, а не содержание ручек: что вызов доехал наружу целиком, что ответ доехал
обратно агенту, и что ожидание не длится вечно. Что именно приложение делает у себя — не наше
дело и проверять это здесь нечем.
"""

import asyncio
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent

from neurobox.box.client_tools import ClientTools, Declared, declarations_of, desk
from neurobox.box.session import current
from neurobox.core.config import settings
from neurobox.model.refusal import RefusalName
from neurobox.sessions.runner import runner


@pytest.fixture(autouse=True)
def clean() -> Any:
    """Стол общий на процесс — между проверками его надо оставлять пустым."""
    desk.declared.clear()
    desk.waiting.clear()
    yield
    desk.declared.clear()
    desk.waiting.clear()


def said(result: CallToolResult) -> str:
    """Текст ответа ручки. Форма содержимого у протокола общая — сужаем её один раз здесь."""
    first = result.content[0]
    assert isinstance(first, TextContent)
    return first.text


def declared(session: str, *names: str) -> None:
    desk.declare(
        session,
        [
            Declared(name=n, description=f"ручка {n}", parameters={"type": "object"})
            for n in names
        ],
    )


def test_declarations_survive_a_sloppy_envelope() -> None:
    """Чужой конверт — чужая форма. Безымянную ручку звать всё равно нечем, а падать не за что."""
    parsed = declarations_of(
        [
            {"name": "save", "description": "сохранить", "parameters": {"type": "object"}},
            {"name": "  ", "description": "безымянная"},
            {"name": "weird", "parameters": "не объект"},
        ]
    )

    assert [(d.name, d.parameters) for d in parsed] == [
        ("save", {"type": "object"}),
        ("weird", {}),
    ]


@pytest.mark.asyncio
async def test_agent_sees_only_the_tools_of_his_own_thread() -> None:
    """Список ручек зависит от разговора: набор объявляют в конверте, и он у каждого свой."""
    declared("поток-1", "save_favorite")
    declared("поток-2", "open_tab")
    server = ClientTools(name="проба")

    token = current.set("поток-1")
    try:
        seen = [tool.name for tool in await server.list_tools()]
    finally:
        current.reset(token)

    assert seen == ["save_favorite"]


@pytest.mark.asyncio
async def test_call_goes_out_and_the_answer_comes_back() -> None:
    """Полный круг: вызов уехал слушателю, ответ приехал агенту."""
    declared("поток-3", "save_favorite")
    server = ClientTools(name="проба")
    queue = runner.subscribe("поток-3")

    token = current.set("поток-3")
    try:
        calling = asyncio.create_task(server.call_tool("save_favorite", {"preset": "синяя"}))

        went = await asyncio.wait_for(queue.get(), timeout=2)
        assert went["event"] == "client-call"
        assert went["tool"] == "save_favorite"
        assert went["arguments"] == {"preset": "синяя"}

        assert desk.answer("поток-3", str(went["call"]), "сохранено, теперь их 7", False)
        result = await asyncio.wait_for(calling, timeout=2)
    finally:
        current.reset(token)
        runner.unsubscribe("поток-3", queue)

    assert result.is_error is False
    assert said(result) == "сохранено, теперь их 7"


@pytest.mark.asyncio
async def test_refusal_of_the_app_reaches_the_agent_as_refusal() -> None:
    """Иначе агент сочтёт действие выполненным и скажет об этом человеку."""
    declared("поток-4", "save_favorite")
    server = ClientTools(name="проба")
    queue = runner.subscribe("поток-4")

    token = current.set("поток-4")
    try:
        calling = asyncio.create_task(server.call_tool("save_favorite", {}))
        went = await asyncio.wait_for(queue.get(), timeout=2)
        desk.answer("поток-4", str(went["call"]), "место кончилось", True)
        result = await asyncio.wait_for(calling, timeout=2)
    finally:
        current.reset(token)
        runner.unsubscribe("поток-4", queue)

    assert result.is_error is True


@pytest.mark.asyncio
async def test_undeclared_tool_is_refused_by_name() -> None:
    """Звать можно только объявленное: иначе агент ждал бы ответа от ручки, которой нет."""
    declared("поток-5", "save_favorite")
    server = ClientTools(name="проба")

    token = current.set("поток-5")
    try:
        result = await server.call_tool("delete_everything", {})
    finally:
        current.reset(token)

    assert result.is_error is True
    assert "delete_everything" in said(result)


@pytest.mark.asyncio
async def test_call_without_a_thread_is_refused() -> None:
    """Позвали мимо развёртки — неизвестно, у кого спрашивать. Молчать нельзя."""
    server = ClientTools(name="проба")

    result = await server.call_tool("save_favorite", {})

    assert result.is_error is True


@pytest.mark.asyncio
async def test_waiting_ends_by_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Вкладку закрывают, и ответа не будет никогда. Агент при этом занят и стоит денег."""
    monkeypatch.setattr(settings, "client_tool_deadline_seconds", 0.05)
    declared("поток-6", "save_favorite")
    server = ClientTools(name="проба")
    stopped: list[tuple[str, RefusalName]] = []

    async def stop(maker: Any, session_id: str, *, refusal: RefusalName, means: str) -> bool:  # noqa: ARG001
        stopped.append((session_id, refusal))
        return True

    monkeypatch.setattr(runner, "stop", stop)

    token = current.set("поток-6")
    try:
        result = await server.call_tool("save_favorite", {})
        # Закрытие прогона идёт отдельной задачей — иначе оно ждало бы возврата отсюда.
        await asyncio.sleep(0.05)
    finally:
        current.reset(token)

    assert result.is_error is True
    assert stopped == [("поток-6", RefusalName.TOOL_ABANDONED)]


@pytest.mark.asyncio
async def test_nobody_waits_for_a_late_answer() -> None:
    """Опоздавший ответ не должен выглядеть доставленным: приложение решит, что агент его увидел."""
    assert desk.answer("поток-7", "вызов-1", "поздно", False) is False


@pytest.mark.asyncio
async def test_two_calls_of_one_tool_get_different_names() -> None:
    """Снаружи по имени вызова связывают просьбу с результатом и строят список сообщений.

    Пока имя было порядковым номером ждущих, счётчик падал обратно на отвеченном вызове, и две
    просьбы одной ручки подряд получали одно имя — то есть схлопывались в один вызов.
    """
    declared("поток-9", "save_favorite")
    server = ClientTools(name="проба")
    queue = runner.subscribe("поток-9")
    names: list[str] = []

    token = current.set("поток-9")
    try:
        for _ in range(2):
            calling = asyncio.create_task(server.call_tool("save_favorite", {}))
            went = await asyncio.wait_for(queue.get(), timeout=2)
            names.append(str(went["call"]))
            desk.answer("поток-9", names[-1], "готово", False)
            await asyncio.wait_for(calling, timeout=2)
    finally:
        current.reset(token)
        runner.unsubscribe("поток-9", queue)

    assert names[0] != names[1]
    assert all(name.startswith("save_favorite-") for name in names)


def test_digest_changes_with_the_set_of_tools() -> None:
    """По отпечатку рантайм узнаёт, что набор сменился, — иначе он до конца сессии не увидит новых."""
    declared("поток-8", "save_favorite")
    before = desk.digest("поток-8")

    declared("поток-8", "save_favorite", "open_tab")

    assert desk.digest("поток-8") != before
