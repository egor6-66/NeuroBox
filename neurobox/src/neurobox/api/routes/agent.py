"""Вход бокса: открытый протокол общения приложения с агентом (AG-UI).

Один запрос — один прогон. Тело несёт поток, прогон, беседу целиком, объявления инструментов и
произвольные свойства; ответ — поток событий со штатными именами протокола.

Своей формы запроса у бокса больше нет, и это решение, а не упрощение. Пока форма была своей,
каждый потребитель писал под неё переходник, а мы изобретали то, что уже стандартизовано: вызов
инструмента, его результат, начало и конец прогона.

Имена потока и прогона называет ПОТРЕБИТЕЛЬ. Двух имён на одну вещь не бывает: заведи мы свои,
ему пришлось бы держать таблицу соответствий и сверять её на каждом событии.

Истории здесь не хранится. Беседа принадлежит тому, кто её ведёт, — приезжает целиком и уезжает
обратно. У нас остаётся слот «последний вход / последний выход»: он спасает результат от
оборванного соединения и не превращается в чужую переписку на наших дисках.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from neurobox.api.deps import CurrentCatalog, CurrentDb, CurrentRegistry
from neurobox.api.identity import Caller
from neurobox.core.config import settings
from neurobox.db.engine import sessions as db_sessions
from neurobox.db.models import Session
from neurobox.sessions import service
from neurobox.sessions.runner import runner

log = logging.getLogger("neurobox.agent")

router = APIRouter(tags=["agent"])


class Message(BaseModel):
    """Реплика беседы. Роли протокольные; лишние поля не описываем — мы их не читаем."""

    id: str | None = None
    role: str
    content: Any = None


class ToolDeclaration(BaseModel):
    name: str
    description: str = ""
    parameters: Any = None


class ContextItem(BaseModel):
    """Что приложение знает о месте, откуда пришла реплика. Пара «о чём» и «что именно»."""

    description: str
    value: str


class RunAgentInput(BaseModel):
    """Конверт протокола. Читаем то, что нам нужно, остальное пропускаем молча.

    Молча — намеренно: протокол растёт, и падать на незнакомом поле значило бы ломаться от
    каждого обновления чужого клиента.
    """

    threadId: str  # noqa: N815 — имена полей протокольные, свои завести нельзя
    runId: str  # noqa: N815
    messages: list[Message] = Field(default_factory=list)
    tools: list[ToolDeclaration] = Field(default_factory=list)
    context: list[ContextItem] = Field(default_factory=list)
    forwardedProps: Any = None  # noqa: N815
    state: Any = None


def _asked(envelope: RunAgentInput) -> str:
    """Что именно уезжает агенту.

    Берётся ПОСЛЕДНЯЯ реплика человека, а не вся беседу. Причина в том, кто помнит: у рантайма с
    готовым агентом память своя, он хранит разговор и пересылает его сам. Пришли мы ему всю
    беседу — в контексте оказались бы две копии, его и наша, и каждый ход удваивал бы счёт.

    Цена названа прямо: переписать прошлое в таком рантайме нельзя. Сжал вчерашнюю реплику —
    агент всё равно помнит, как было. Рантайм с сырой моделью, где памяти нет ни у кого,
    приезжает своим паспортом и берёт беседу целиком — это отдельная работа.
    """
    for message in reversed(envelope.messages):
        if message.role != "user":
            continue

        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            # Составная реплика: берём текстовые части, остальное (картинки, файлы) пока не наше.
            parts = [
                str(piece.get("text", ""))
                for piece in content
                if isinstance(piece, dict) and piece.get("type") == "text"
            ]
            return "".join(parts)

    return ""


def _context(envelope: RunAgentInput) -> dict[str, str]:
    """Данные приложения о месте работы — помеченными, а не склеенными с репликой.

    Склей их с текстом, и агент начнёт на них отвечать: «да, вижу, вы на странице кнопки».
    """
    return {item.description: item.value for item in envelope.context if item.description.strip()}


def _named(envelope: RunAgentInput) -> tuple[str, str, str]:
    """Чем думать и с чем работать. Приезжает в свойствах конверта, умолчания — из настроек.

    Отдельного «завести поток» протокол не знает: он просто называет поток в каждом запросе.
    Значит и рецепт называется там же, а не запоминается однажды при создании.
    """
    props = envelope.forwardedProps if isinstance(envelope.forwardedProps, dict) else {}

    return (
        str(props.get("recipe") or settings.default_recipe),
        str(props.get("passport") or settings.default_passport),
        str(props.get("agent") or settings.default_agent),
    )


def _frame(kind: str, **fields: Any) -> dict[str, str]:
    """Кадр протокола. Тип лежит ВНУТРИ данных, а не в имени события SSE.

    Так велит протокол, и это не мелочь: клиент разбирает один поток однородных объектов и не
    обязан подписываться на каждое имя отдельно.
    """
    return {"data": json.dumps({"type": kind, **fields}, ensure_ascii=False)}


async def _stream(
    envelope: RunAgentInput, reply_id: str, queue: asyncio.Queue[dict[str, object]]
) -> AsyncIterator[dict[str, str]]:
    """Перевести наши события в события протокола.

    Перевод живёт ЗДЕСЬ, а не в прогоне: прогон не должен знать, каким протоколом его слушают,
    иначе второй протокол потребует править и его.

    Очередь приходит ГОТОВОЙ: подписались до запуска прогона. Подпишись мы здесь, быстрый прогон
    успел бы отработать раньше слушателя, и клиент не увидел бы ни шагов, ни итога — потеря,
    которую в коде не видно, а видно только по пустым быстрым прогонам.
    """
    calls = 0

    yield _frame("RUN_STARTED", threadId=envelope.threadId, runId=envelope.runId)
    try:
        while True:
            event = await queue.get()
            kind = str(event.get("event"))

            if kind == "run-step":
                step = str(event.get("kind") or "")
                tool = event.get("tool")

                if step == "using" and tool:
                    calls += 1
                    call = f"{envelope.runId}-{calls}"
                    yield _frame("TOOL_CALL_START", toolCallId=call, toolCallName=str(tool))
                    yield _frame(
                        "TOOL_CALL_ARGS",
                        toolCallId=call,
                        delta=json.dumps(event.get("arguments") or {}, ensure_ascii=False),
                    )
                    yield _frame("TOOL_CALL_END", toolCallId=call)
                    continue

                if step == "result":
                    # Идентификатор вызова здесь ЧУЖОЙ — его дал рантайм. Своей нумерацией его не
                    # подменить: снаружи по нему связывают результат с просьбой, а два разных
                    # счёта не сойдутся.
                    yield _frame(
                        "TOOL_CALL_RESULT",
                        messageId=reply_id,
                        toolCallId=str(event.get("call") or ""),
                        content=str(event.get("text") or ""),
                        role="tool",
                    )
                    continue

                # Прочие шаги — слова агента по ходу дела. Ход мысли, а не итог: клиент вправе
                # показать их и вправе не показывать.
                if event.get("text"):
                    yield _frame(
                        "TEXT_MESSAGE_CHUNK",
                        messageId=reply_id,
                        role="assistant",
                        delta=str(event["text"]),
                    )
                continue

            if kind in ("run-finished", "run-canceled"):
                refusal = event.get("refusal")
                if refusal:
                    # Отказ приезжает ИМЕНОВАННЫМ. «Что-то пошло не так» нельзя ни показать
                    # человеку, ни обработать клиенту.
                    yield _frame(
                        "RUN_ERROR",
                        message=str(event.get("means") or refusal),
                        code=str(refusal),
                    )
                    return

                reply = str(event.get("reply") or "")
                if reply:
                    yield _frame("TEXT_MESSAGE_START", messageId=reply_id, role="assistant")
                    yield _frame("TEXT_MESSAGE_CONTENT", messageId=reply_id, delta=reply)
                    yield _frame("TEXT_MESSAGE_END", messageId=reply_id)

                yield _frame("RUN_FINISHED", outcome="success", result=reply)
                return
    finally:
        runner.unsubscribe(envelope.threadId, queue)


@router.post("/agent")
async def run(
    envelope: RunAgentInput,
    caller: Caller,
    db: CurrentDb,
    catalog: CurrentCatalog,
    registry: CurrentRegistry,
) -> EventSourceResponse:
    """Прогнать один ход и отдать его потоком событий."""
    asked = _asked(envelope).strip()
    if not asked:
        raise HTTPException(status_code=422, detail="в конверте нет реплики человека")

    recipe_name, passport_name, agent_name = _named(envelope)
    for kind, name, known in (
        ("рецепта", recipe_name, catalog.recipes),
        ("паспорта", passport_name, catalog.passports),
        ("агента", agent_name, catalog.agents),
    ):
        if name not in known:
            raise HTTPException(status_code=400, detail=f"{kind} {name!r} нет в каталоге")

    try:
        session = await service.opened(
            db,
            thread_id=envelope.threadId,
            owner_id=caller.owner_id,
            recipe=recipe_name,
            passport=passport_name,
            agent=agent_name,
        )
    except service.Missing as missing:
        # Чужой поток — отказ словами, а не пятисотая. Имя потока придумывает потребитель, и
        # совпадение имён у двух людей вопрос времени, а не редкость.
        raise HTTPException(status_code=409, detail=missing.refusal.means) from missing

    # Недостающее опрашивается ЗДЕСЬ: реестр живёт в памяти процесса и после перезапуска пуст.
    # Раньше развёртка молча собиралась без неопрошенного сервера, агент оставался без ручек и
    # честно отвечал, что ничего не умеет, — виноватым выглядел он.
    recipe = catalog.recipes[recipe_name]
    await registry.ensure([catalog.seeds[n] for n in recipe.seeds if n in catalog.seeds])
    probes = {p.seed: p for p in registry.known()}

    # Подписка ДО запуска: иначе быстрый прогон успеет закончиться раньше, чем появится
    # слушатель, и клиент получит пустой поток при выполненной работе.
    queue = runner.subscribe(envelope.threadId)
    try:
        await runner.start(
            db_sessions(), session, catalog, probes, asked, envelope.runId, _context(envelope)
        )
    except service.Missing as missing:
        runner.unsubscribe(envelope.threadId, queue)
        raise HTTPException(status_code=409, detail=missing.refusal.means) from missing
    except Exception:
        runner.unsubscribe(envelope.threadId, queue)
        raise

    return EventSourceResponse(
        _stream(envelope, reply_id=f"msg-{envelope.runId}", queue=queue)
    )


class Spent(BaseModel):
    """Сколько стоил поток. Единственное, что бокс знает о разговоре после его окончания."""

    thread: str
    runs: int
    prompt_tokens: int
    completion_tokens: int
    cache_read_tokens: int
    cost_micros: int


@router.get("/agent/{thread_id}/spent")
async def spent(thread_id: str, caller: Caller, db: CurrentDb) -> Spent:
    """Расход по потоку. На этом стоят квоты, поэтому счётчик остаётся, когда история ушла."""
    session = await service.by_id(db, thread_id, caller.owner_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"потока {thread_id!r} нет")

    runs = await service.runs_of(db, thread_id)
    return Spent(
        thread=thread_id,
        runs=len(runs),
        prompt_tokens=sum(r.prompt_tokens or 0 for r in runs),
        completion_tokens=sum(r.completion_tokens or 0 for r in runs),
        cache_read_tokens=sum(r.cache_read_tokens or 0 for r in runs),
        cost_micros=sum(r.cost_micros or 0 for r in runs),
    )


@router.post("/agent/{thread_id}/cancel")
async def cancel(thread_id: str, caller: Caller, db: CurrentDb) -> dict[str, bool]:
    """Прервать то, что идёт в потоке прямо сейчас.

    Отдельным запросом, а не полем конверта: останавливают уже начатое, и решение об остановке
    приходит тогда, когда прогон работает.
    """
    session: Session | None = await service.by_id(db, thread_id, caller.owner_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"потока {thread_id!r} нет")

    runs = await service.runs_of(db, thread_id)
    working = [r for r in runs if r.state.value == "working"]
    stopped = False
    for r in working:
        stopped = await runner.cancel(db_sessions(), r.id) or stopped

    return {"stopped": stopped}
