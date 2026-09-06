"""Наши собственные MCP-серверы: что агент может нам сказать и как это доезжает."""

from collections.abc import MutableMapping
from typing import Any

import pytest
from fastapi.testclient import TestClient

from neurobox.box.registry import OWN, by_name, connection
from neurobox.box.session import HEADER, Mount, current
from neurobox.main import app
from neurobox.model.catalog import merge
from neurobox.model.entities import Layer, Passport, Recipe, ServerSeed
from neurobox.model.files import LayerContents
from neurobox.model.unfold import unfold


def test_our_servers_are_named_in_latin() -> None:
    """Из имени склеивается идентификатор инструмента у агента.

    Кириллическое имя туда не проходит: сервер молча оказывается невидимым, и понять это можно
    только спросив агента, что он видит.
    """
    for own in OWN:
        assert own.name.isascii()
        assert own.name.replace("-", "").replace("_", "").isalnum()


def test_address_is_the_same_for_probe_and_unfold() -> None:
    """Опрос и развёртка обязаны ходить по одному адресу.

    Разойдутся — список ручек в пульте окажется не тем, что получит агент, и человек будет
    чинить не то, что сломано.
    """
    probing = connection("notes")
    running = connection("notes", session_id="с-1")

    assert probing["url"] == running["url"]


def test_session_travels_in_the_header_not_in_the_answer() -> None:
    """Спрашивать у агента, где он находится, значило бы доверять его догадке о контексте."""
    entry = connection("notes", session_id="с-1")

    assert entry["headers"][HEADER.decode()] == "с-1"


def test_probing_carries_no_session() -> None:
    """При опросе сессии нет, и подставлять пустую значило бы записывать заметки в никуда."""
    assert "headers" not in connection("notes")


def test_unknown_server_gives_nothing_not_a_broken_address() -> None:
    assert connection("такого-нет") == {}
    assert by_name("такого-нет") is None


def test_our_seed_reaches_the_agent_with_the_session() -> None:
    """Развёртка подставляет адрес и сессию: в файле их записать нельзя."""
    contents = LayerContents(Layer.BUILTIN)
    contents.seeds["notes"] = ServerSeed(
        name="notes", layer=Layer.BUILTIN, server={"type": "http", "own": "notes"}
    )
    recipe = Recipe(name="р", layer=Layer.FILE, seeds=["notes"])
    contents.recipes["р"] = recipe
    catalog = merge([contents])
    passport = Passport(name="п", layer=Layer.FILE, provider="claude-code", model="m")

    unfolded = unfold(catalog, recipe, passport, {}, session_id="с-7")

    assert [p.seed for p in unfolded.servers] == ["notes"]
    assert unfolded.servers[0].server["headers"][HEADER.decode()] == "с-7"


def test_our_seed_needs_no_probe_to_reach_the_agent() -> None:
    """Мы и есть источник этих серверов: спрашивать себя же по сети — работа ради работы."""
    contents = LayerContents(Layer.BUILTIN)
    contents.seeds["notes"] = ServerSeed(
        name="notes", layer=Layer.BUILTIN, server={"type": "http", "own": "notes"}
    )
    recipe = Recipe(name="р", layer=Layer.FILE, seeds=["notes"])
    contents.recipes["р"] = recipe
    catalog = merge([contents])
    passport = Passport(name="п", layer=Layer.FILE, provider="claude-code", model="m")

    # Реестр опросов пуст — обычный сервер тут получил бы отказ not-probed.
    unfolded = unfold(catalog, recipe, passport, {}, session_id="с-8")

    assert unfolded.refusals == []


Scope = MutableMapping[str, Any]


async def _never() -> MutableMapping[str, Any]:
    raise AssertionError("получение сообщений не должно происходить")


async def _nothing(message: MutableMapping[str, Any]) -> None:  # noqa: ARG001
    raise AssertionError("отправка не должна происходить")


@pytest.mark.asyncio
async def test_mount_refuses_before_startup() -> None:
    """Обращение до старта — состояние, которого быть не должно, и молчать о нём нельзя."""
    mount = Mount()

    with pytest.raises(RuntimeError, match="ещё не поднят"):
        await mount({"type": "http", "headers": []}, _never, _nothing)


@pytest.mark.asyncio
async def test_session_is_seen_inside_and_gone_after() -> None:
    """Сброс обязателен: без него следующий запрос получил бы чужую сессию, и заметка ушла бы
    не в тот разговор — молча."""
    seen: list[str | None] = []

    async def inside(scope: Scope, receive: object, send: object) -> None:  # noqa: ARG001
        seen.append(current.get())

    mount = Mount()
    mount.use(inside)

    # Заголовки HTTP — байты латиницей: кириллица в них не проходит вовсе, и настоящие
    # идентификаторы сессий её не несут.
    await mount({"type": "http", "headers": [(HEADER, b"s-9")]}, _never, _nothing)

    assert seen == ["s-9"]
    assert current.get() is None


def test_our_servers_survive_a_second_startup() -> None:
    """Менеджер сессий протокола запускается один раз на экземпляр.

    Собранное при импорте приложение переживает только первый запуск; второй падает с
    невнятной ошибкой, и в тестах это единственное место, где такое вообще заметно.
    """
    with TestClient(app):
        pass
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
