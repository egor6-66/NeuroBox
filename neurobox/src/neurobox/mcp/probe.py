"""Опрос MCP-сервера: что он даёт и жив ли он вообще.

Паспорт сервера НЕ пишется у нас руками — он вычитывается у самого сервера. Продублированное
описание разъехалось бы с ним при первом же обновлении, и никто бы этого не заметил.

Второй смысл опроса прямее: «прописан, но не отвечает» выясняется здесь, а не в середине
прогона за потраченные токены.

Неудача опроса — не исключение, а названный отказ: сервер снаружи, он вправе лежать, и это
нормальный ход событий, о котором человеку надо сказать словами.
"""

import json
import math
from datetime import UTC, datetime
from typing import Any

import httpx2
from mcp import ClientSession

# `create_mcp_http_client` — задокументированный помощник пакета, но его забыли внести в
# `__all__` модуля, поэтому строгая проверка типов его не видит. Помечаем ровно эту строку,
# а не глушим проверку целиком: собирать клиента самим значило бы копировать вендорские
# умолчания (follow_redirects, таймауты под SSE) и разъехаться с ними при обновлении.
from mcp.client.streamable_http import (  # type: ignore[attr-defined]
    create_mcp_http_client,
    streamable_http_client,
)
from pydantic import BaseModel, Field

from neurobox.model.entities import ServerSeed
from neurobox.model.refusal import Refusal, RefusalName

CHARS_PER_TOKEN = 4
"""Грубая оценка: сколько символов описания приходится на токен.

Намеренное упрощение, а не расчёт. Годится РОВНО потому, что цифра нужна для подсказки,
которая никогда не блокирует запуск. Появится проверка, что-то запрещающая, — здесь должен
встать настоящий токенизатор той модели, о которой идёт речь, а не эта константа.
"""


class ToolBrief(BaseModel):
    name: str
    description: str | None = None

    input_schema: dict[str, Any] = Field(default_factory=dict)
    """Схема входа, как её объявил сервер. Нужна, чтобы построить форму вызова: без неё
    человеку пришлось бы писать аргументы вслепую, а нам — угадывать их состав."""


class Probe(BaseModel):
    """Что удалось узнать у сервера. Живёт рядом с семенем, а не внутри него."""

    seed: str
    at: datetime

    ok: bool
    tools: list[ToolBrief] = Field(default_factory=list)
    instructions: str | None = None

    weight_chars: int = 0
    """Длина описания сервера: перечень тулзов плюс инструкция."""

    refusals: list[Refusal] = Field(default_factory=list)

    @property
    def weight_tokens(self) -> int:
        """Во сколько примерно обойдётся присутствие этого сервера в контексте."""
        return math.ceil(self.weight_chars / CHARS_PER_TOKEN)


def _now() -> datetime:
    return datetime.now(UTC)


def _refused(seed: str, refusals: list[Refusal]) -> Probe:
    return Probe(seed=seed, at=_now(), ok=False, refusals=refusals)


def _weigh(tools: list[ToolBrief], instructions: str | None) -> int:
    """Вес описания сервера в контексте агента.

    Схема входа считается наравне с описанием: агент видит её целиком, и у инструмента с
    десятком полей она весит больше, чем весь текст вокруг.
    """
    total = len(instructions or "")
    for tool in tools:
        total += len(tool.name) + len(tool.description or "")
        total += len(json.dumps(tool.input_schema, ensure_ascii=False)) if tool.input_schema else 0
    return total


def _explain(error: BaseException) -> str:
    """Развернуть исключение до настоящей причины.

    Асинхронный клиент заворачивает сбои в группы задач, и наружу торчит
    «unhandled errors in a TaskGroup» — текст, не говорящий человеку ничего.
    Отказ обязан объяснять, поэтому группа разбирается до листьев.
    """
    leaves: list[str] = []

    def walk(current: BaseException) -> None:
        nested = getattr(current, "exceptions", None)
        if isinstance(nested, (list, tuple)) and nested:
            for inner in nested:
                if isinstance(inner, BaseException):
                    walk(inner)
            return
        text = str(current).strip()
        leaves.append(f"{type(current).__name__}: {text}" if text else type(current).__name__)

    walk(error)
    # Дубликаты убираются с сохранением порядка: пять одинаковых отказов соединения
    # читаются не лучше одного.
    seen: dict[str, None] = dict.fromkeys(leaves)
    return "; ".join(seen)


def _http_target(entry: dict[str, Any]) -> tuple[str | None, dict[str, str]]:
    url = entry.get("url")
    headers = entry.get("headers") or {}
    return (url if isinstance(url, str) else None), {
        str(k): str(v) for k, v in headers.items() if isinstance(headers, dict)
    }


class Called(BaseModel):
    """Что вернул инструмент при ручном вызове."""

    ok: bool
    """Отказ САМОГО инструмента, а не протокола: отрицательный отчёт проверки — это `ok: true`
    с содержимым, а `ok: false` значит «ручка не сделала того, что просили»."""

    content: list[dict[str, Any]] = Field(default_factory=list)
    structured: dict[str, Any] | None = None
    refusals: list[Refusal] = Field(default_factory=list)


async def call_tool(
    seed: ServerSeed, tool: str, arguments: dict[str, Any], timeout_seconds: float = 120.0
) -> Called:
    """Дёрнуть инструмент вручную, минуя агента.

    Нужно, чтобы человек мог проверить саму ручку отдельно от того, правильно ли ей
    распорядился агент: иначе при поломке непонятно, кто из двоих виноват.
    """
    if seed.refusals:
        return Called(ok=False, refusals=list(seed.refusals))

    url, headers = _http_target(seed.server)
    if url is None:
        return Called(
            ok=False,
            refusals=[
                Refusal(
                    name=RefusalName.TRANSPORT_UNSUPPORTED,
                    means="у семени нет адреса: вручную дёргать можно только серверы по http",
                    where=seed.name,
                )
            ],
        )

    try:
        http = create_mcp_http_client(
            headers=headers or None, timeout=httpx2.Timeout(timeout_seconds)
        )
        async with (
            streamable_http_client(url, http_client=http) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool(tool, arguments)
    except Exception as error:  # noqa: BLE001 — сервер снаружи
        return Called(
            ok=False,
            refusals=[
                Refusal(
                    name=RefusalName.SERVER_SILENT,
                    means=f"инструмент не ответил: {_explain(error)}",
                    where=f"{url} · {tool}",
                )
            ],
        )

    content = [
        block.model_dump(mode="json") if hasattr(block, "model_dump") else {"text": str(block)}
        for block in (result.content or [])
    ]
    return Called(
        ok=not result.is_error,
        content=content,
        structured=dict(result.structured_content) if result.structured_content else None,
    )


async def probe(seed: ServerSeed, timeout_seconds: float = 15.0) -> Probe:
    """Опросить один сервер. Любая неудача возвращается значением, а не броском."""
    # Семя, которое уже не сложилось при чтении (нет токена), не опрашивается: запрос без
    # подставленного токена дал бы 401 и увёл бы причину в сторону от настоящей.
    if seed.refusals:
        return _refused(seed.name, list(seed.refusals))

    url, headers = _http_target(seed.server)
    if url is None:
        return _refused(
            seed.name,
            [
                Refusal(
                    name=RefusalName.TRANSPORT_UNSUPPORTED,
                    means=(
                        "у семени нет адреса: рантайм говорит только по http, "
                        "а stdio-серверы поднимает сайдкар"
                    ),
                    where=seed.name,
                )
            ],
        )

    try:
        # Таймаут ужимается против вендорского умолчания (300 секунд на чтение под длинные SSE):
        # опрос — короткий вопрос, и висеть на нём минутами незачем.
        http = create_mcp_http_client(
            headers=headers or None, timeout=httpx2.Timeout(timeout_seconds)
        )
        async with (
            streamable_http_client(url, http_client=http) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            initialized = await session.initialize()
            listed = await session.list_tools()
    except Exception as error:  # noqa: BLE001 — сервер снаружи, падать он вправе как угодно
        return _refused(
            seed.name,
            [
                Refusal(
                    name=RefusalName.SERVER_SILENT,
                    means=f"сервер не ответил: {_explain(error)}",
                    where=url,
                )
            ],
        )

    tools = [
        ToolBrief(
            name=t.name,
            description=t.description,
            input_schema=dict(t.input_schema or {}),
        )
        for t in listed.tools
    ]
    return Probe(
        seed=seed.name,
        at=_now(),
        ok=True,
        tools=tools,
        instructions=initialized.instructions,
        weight_chars=_weigh(tools, initialized.instructions),
    )
