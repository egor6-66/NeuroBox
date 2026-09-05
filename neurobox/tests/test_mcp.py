"""Опрос и реестр. Настоящая сеть здесь не нужна: проверяется поведение, а не чужой сервер."""

import asyncio
from datetime import UTC, datetime

import pytest

from neurobox.mcp import probe as probe_module
from neurobox.mcp.probe import Probe, ToolBrief, probe
from neurobox.mcp.registry import Registry
from neurobox.model.entities import KnowledgeSeed, Layer, ServerSeed
from neurobox.model.refusal import Refusal, RefusalName


def server(name: str = "s", **entry: object) -> ServerSeed:
    return ServerSeed(name=name, layer=Layer.FILE, server=dict(entry))


# --- отказы опроса ---------------------------------------------------------


@pytest.mark.anyio
async def test_stdio_seed_refused_by_name_not_attempted() -> None:
    result = await probe(server(command="npx", args=["-y", "@ark-ui/mcp"]))

    assert result.ok is False
    assert [r.name for r in result.refusals] == [RefusalName.TRANSPORT_UNSUPPORTED]


@pytest.mark.anyio
async def test_seed_with_reading_refusal_is_not_probed() -> None:
    """Нет токена — запрос дал бы 401 и увёл бы причину в сторону от настоящей."""
    broken = server(url="http://127.0.0.1:1/mcp")
    broken.refusals.append(Refusal(name=RefusalName.ENV_MISSING, means="нет переменной"))

    result = await probe(broken)

    assert result.ok is False
    assert [r.name for r in result.refusals] == [RefusalName.ENV_MISSING]


@pytest.mark.anyio
async def test_unreachable_server_refuses_by_name_not_raises() -> None:
    # Порт 1 закрыт всегда — соединение отвергается сразу, без ожидания таймаута.
    result = await probe(server(url="http://127.0.0.1:1/mcp"), timeout_seconds=2)

    assert result.ok is False
    assert [r.name for r in result.refusals] == [RefusalName.SERVER_SILENT]
    assert "не ответил" in result.refusals[0].means


# --- вес описания ----------------------------------------------------------


def test_weight_counts_tools_and_instructions() -> None:
    result = Probe(
        seed="s",
        at=datetime.now(UTC),
        ok=True,
        tools=[ToolBrief(name="ab", description="cd")],
        instructions="ef",
        weight_chars=6,
    )

    # Оценка грубая намеренно: цифра нужна подсказке, которая ничего не запрещает.
    assert result.weight_tokens == 2


# --- реестр ----------------------------------------------------------------


@pytest.mark.anyio
async def test_refresh_all_skips_knowledge_seeds() -> None:
    registry = Registry()
    seeds = [
        KnowledgeSeed(name="знание", layer=Layer.FILE, text="…"),
        server("сервер", command="npx"),
    ]

    results = await registry.refresh_all(seeds)

    assert [r.seed for r in results] == ["сервер"]


@pytest.mark.anyio
async def test_refresh_all_runs_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Зависший адрес не должен задерживать остальные — иначе опрос реестра бесполезно долог."""

    # Подпись повторяет настоящую: подмена, разошедшаяся с оригиналом, проверяла бы не то.
    async def slow(seed: ServerSeed, timeout_seconds: float = 15.0) -> Probe:  # noqa: ARG001
        await asyncio.sleep(0.2)
        return Probe(seed=seed.name, at=datetime.now(UTC), ok=True)

    monkeypatch.setattr(probe_module, "probe", slow)
    monkeypatch.setattr("neurobox.mcp.registry.probe", slow)

    registry = Registry()
    seeds = [server(f"с{i}", url="http://x") for i in range(5)]

    started = asyncio.get_running_loop().time()
    await registry.refresh_all(list(seeds))
    spent = asyncio.get_running_loop().time() - started

    # Последовательно вышло бы около секунды; параллельно — около одного шага.
    assert spent < 0.6


def test_registry_remembers_last_answer() -> None:
    registry = Registry()
    first = Probe(seed="s", at=datetime.now(UTC), ok=False)
    second = Probe(seed="s", at=datetime.now(UTC), ok=True)

    registry.remember(first)
    registry.remember(second)

    assert registry.get("s") is second
    assert len(registry.known()) == 1


def test_explanation_unwraps_task_group_noise() -> None:
    """«unhandled errors in a TaskGroup» человеку не говорит ничего — нужна настоящая причина."""
    from neurobox.mcp.probe import _explain

    inner = ConnectionRefusedError("All connection attempts failed")
    grouped = ExceptionGroup("unhandled errors in a TaskGroup", [inner])

    explained = _explain(grouped)

    assert "ConnectionRefusedError" in explained
    assert "All connection attempts failed" in explained
    assert "TaskGroup" not in explained


def test_explanation_collapses_identical_causes() -> None:
    same = [TimeoutError("вышло время"), TimeoutError("вышло время")]

    assert _explain_count(ExceptionGroup("g", same)) == 1


def _explain_count(error: BaseException) -> int:
    from neurobox.mcp.probe import _explain

    return len(_explain(error).split("; "))
