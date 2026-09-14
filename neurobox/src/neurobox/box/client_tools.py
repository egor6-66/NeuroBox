"""Ручки, которые живут у ПОТРЕБИТЕЛЯ, а не у нас.

Есть действия, которых на сервере просто нет: избранное в `localStorage`, состояние экрана,
выбранная вкладка. Раньше агенту они были недоступны вовсе — либо приходилось тащить их в
MCP-зону только ради того, чтобы их можно было позвать.

Здесь бокс работает ПОЧТАЛЬОНОМ, а не исполнителем. Агент зовёт ручку как любую другую, мы
передаём вызов наружу потоком событий, потребитель исполняет у себя и приносит результат
отдельным запросом. Что именно он там сделал — не наше дело и не наша ответственность.

> [!NOTE]
> Эти ручки НЕ проходят через рецепт, и это решение, а не упущение. Рецепт — граница НАШИХ зон:
> он отвечает на вопрос, что бокс даёт агенту. Здесь же потребитель открывает агенту свои
> собственные ручки, в том же запросе, своей рукой. Спрашивать у рецепта разрешения на это
> значило бы, что человек должен править файл на сервере, чтобы разрешить себе своё же.

Почему настоящим MCP-сервером, а не уговором в инструкции: агент обязан ВИДЕТЬ ручку наравне с
остальными. Описание в тексте держалось бы на том, что он не забудет формат, — а забытый формат
это молча несделанное действие.
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, TextContent, Tool

from neurobox.box.session import current
from neurobox.core.config import settings

log = logging.getLogger("neurobox.box")

NAME = "client"
"""Имя зоны у агента: ручки видны ему как `mcp__client__<имя>`.

Латиницей обязательно — из имени склеивается имя инструмента, и кириллица туда не проходит.
"""

PREFIX = f"mcp__{NAME}__"
"""По этой приставке поток событий узнаёт свои вызовы среди чужих."""

INSTRUCTIONS = """
Ручки этой зоны исполняет не сервер, а приложение, из которого с тобой говорят, — прямо на
устройстве человека. Зови их так же, как любые другие.

Ответ приходит не мгновенно: на той стороне выполняется настоящее действие. Это нормально.

Если ручка ответила отказом — значит действие не сделано. Не считай его выполненным и скажи
человеку правду.
""".strip()


@dataclass(frozen=True)
class Declared:
    """Ручка, объявленная потребителем в конверте прогона."""

    name: str
    description: str
    parameters: dict[str, Any]

    def shown(self) -> Tool:
        """Как её увидит агент.

        Схему не проверяем и не переписываем: она принадлежит объявившему. Наше дело — донести
        её до агента без потерь, а не иметь мнение о чужих ручках.
        """
        return Tool(
            name=self.name,
            description=self.description or f"Ручка приложения {self.name!r}",
            # Пустая схема без `properties` разваливает часть рантаймов: объект без полей —
            # это объект, а не отсутствие схемы.
            input_schema=self.parameters or {"type": "object", "properties": {}},
        )


def declarations_of(tools: list[dict[str, Any]] | None) -> list[Declared]:
    """Разобрать объявления из конверта. Безымянные пропускаются молча — звать их всё равно нечем."""
    out: list[Declared] = []
    for item in tools or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        parameters = item.get("parameters")
        out.append(
            Declared(
                name=name,
                description=str(item.get("description") or "").strip(),
                parameters=parameters if isinstance(parameters, dict) else {},
            )
        )
    return out


@dataclass
class Desk:
    """Стол, за которым ждут ответа потребителя.

    Живёт в памяти процесса, как и сами прогоны. Переживать рестарт ему незачем: вместе с
    процессом умирает и прогон, которого ждали, — воскрешать ожидание не для кого.
    """

    declared: dict[str, list[Declared]] = field(default_factory=dict)
    """Что объявлено по каждому потоку. Перезаписывается каждым ходом: набор ручек называют в
    конверте, и прошлый ход не вправе решать за нынешний."""

    waiting: dict[tuple[str, str], asyncio.Future[tuple[str, bool]]] = field(default_factory=dict)
    """Вызовы, которые сейчас ждут ответа: поток и вызов — ключ."""

    def declare(self, session_id: str, tools: list[Declared]) -> None:
        if tools:
            self.declared[session_id] = tools
        else:
            self.declared.pop(session_id, None)

    def tools_of(self, session_id: str | None) -> list[Declared]:
        return self.declared.get(session_id or "", [])

    def digest(self, session_id: str) -> str:
        """Отпечаток набора ручек.

        Уезжает в объявление сервера, и потому смена набора видна рантайму как смена развёртки.
        Без этого агент, поднятый с прежним набором, не узнал бы о новых ручках: список он
        спрашивает при подключении, а подключение живёт столько же, сколько процесс.

        Цена названа: сменил потребитель набор — процесс поднимется заново и потеряет состояние
        MCP-зон. Набор ручек это свойство версии приложения, а не хода, так что платится она
        редко — но платится, и прятать её незачем.
        """
        shape = [(d.name, d.description, d.parameters) for d in self.tools_of(session_id)]
        raw = json.dumps(shape, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    async def ask(self, session_id: str, call_id: str, tool: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Передать вызов наружу и дождаться ответа.

        Возвращает текст ответа и признак отказа. Ждать вечно нельзя: см. `client_tool_deadline_seconds`.
        """
        loop = asyncio.get_running_loop()
        answer: asyncio.Future[tuple[str, bool]] = loop.create_future()
        self.waiting[(session_id, call_id)] = answer

        from neurobox.sessions.runner import runner

        runner.tell(
            session_id,
            {
                "event": "client-call",
                "call": call_id,
                "tool": tool,
                "arguments": arguments,
            },
        )

        try:
            return await asyncio.wait_for(answer, timeout=settings.client_tool_deadline_seconds)
        finally:
            self.waiting.pop((session_id, call_id), None)

    def answer(self, session_id: str, call_id: str, content: str, failed: bool) -> bool:
        """Принести ответ. Возвращает, ждал ли его кто-нибудь."""
        pending = self.waiting.get((session_id, call_id))
        if pending is None or pending.done():
            return False

        pending.set_result((content, failed))
        return True

    def pending_of(self, session_id: str) -> list[str]:
        return [call for (thread, call) in self.waiting if thread == session_id]


desk = Desk()
"""Один стол на процесс — как и реестр прогонов, которому он служит."""


class ClientTools(MCPServer):
    """Сервер, у которого нет ни одной своей ручки.

    Список и исполнение подменяются целиком, а не собираются декоратором: ручки приходят от
    потребителя во время работы, а декоратор описывает известное заранее. Схема у них чужая —
    превратить её в подпись функции на Python нельзя, да и незачем: проверять её будет тот, кто
    её объявил.
    """

    async def list_tools(self) -> list[Tool]:
        return [item.shown() for item in desk.tools_of(current.get())]

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[Any, Any] | None = None
    ) -> CallToolResult:
        session_id = current.get()
        if not session_id:
            # Позвали мимо развёртки: непонятно, у кого спрашивать. Молчаливое согласие оставило
            # бы агента в уверенности, что действие выполнено.
            return _refused("Ручка не выполнена: неизвестно, к какому разговору относится вызов.")

        known = {item.name for item in desk.tools_of(session_id)}
        if name not in known:
            return _refused(f"Ручки {name!r} приложение не объявляло.")

        call_id = f"{session_id}:{len(desk.pending_of(session_id))}:{name}"
        log.info("вызов ручки приложения", extra={"session": session_id, "tool": name})

        try:
            content, failed = await desk.ask(session_id, call_id, name, arguments)
        except TimeoutError:
            # Ответа не будет: приложение ушло. Прогон при этом не должен продолжаться — агент
            # занят, а читать его ответ уже некому; закрывает прогон тот, кто ждал, см.
            # `_abandon`.
            log.warning("ручку приложения никто не выполнил", extra={"session": session_id, "tool": name})
            _abandon(session_id, name)
            return _refused(
                f"Ручка {name!r} не выполнена: приложение не ответило. Действие НЕ сделано."
            )

        return CallToolResult(content=[TextContent(type="text", text=content)], is_error=failed)


def _refused(text: str) -> CallToolResult:
    """Отказ ручки. Агент обязан узнать, что действие не сделано, а не догадываться по молчанию."""
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)


def _abandon(session_id: str, tool: str) -> None:
    """Закрыть прогон, которого больше некому дождаться.

    Отдельной задачей, а не здесь же: закрытие прогона ждёт, пока свернётся исполняющая его
    задача, а та ждёт агента, который ждёт ВОЗВРАТА ИЗ ЭТОЙ ФУНКЦИИ. Дождались бы взаимной
    блокировки, в которой не виноват никто по отдельности.
    """
    from neurobox.db.engine import sessions
    from neurobox.model.refusal import RefusalName
    from neurobox.sessions.runner import runner

    async def close() -> None:
        await runner.stop(
            sessions(),
            session_id,
            refusal=RefusalName.TOOL_ABANDONED,
            means=f"приложение не выполнило ручку {tool!r} и не ответило",
        )

    task = asyncio.create_task(close())
    # Ссылка держится до конца: задача без ссылок может быть убрана сборщиком мусора посреди
    # работы, и прогон остался бы висеть — редко и невоспроизводимо.
    _closing.add(task)
    task.add_done_callback(_closing.discard)


_closing: set[asyncio.Task[None]] = set()


def build() -> MCPServer:
    return ClientTools(name="neurobox-client-tools", instructions=INSTRUCTIONS)
