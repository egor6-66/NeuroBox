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

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from neurobox.api.deps import CurrentCatalog, CurrentDb, CurrentRegistry
from neurobox.api.identity import Caller
from neurobox.api.relay import Relay, frame, relays
from neurobox.box.client_tools import PREFIX as CLIENT_PREFIX
from neurobox.box.client_tools import desk
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


async def _translate(
    envelope: RunAgentInput,
    reply_id: str,
    queue: asyncio.Queue[dict[str, object]],
    relay: Relay,
) -> None:
    """Перевести наши события в события протокола и отдать их пересказчику.

    Перевод живёт ЗДЕСЬ, а не в прогоне: прогон не должен знать, каким протоколом его слушают,
    иначе второй протокол потребует править и его.

    И НЕ внутри HTTP-ответа: пока он жил там, оборванное соединение оставляло прогон без
    переводчика — работа шла, деньги тратились, а кадры уходили в пустоту. Теперь перевод живёт
    столько же, сколько прогон, а соединения приходят и уходят.

    Очередь приходит ГОТОВОЙ: подписались до запуска прогона. Подпишись мы здесь, быстрый прогон
    успел бы отработать раньше слушателя, и клиент не увидел бы ни шагов, ни итога — потеря,
    которую в коде не видно, а видно только по пустым быстрым прогонам.
    """
    calls = 0
    # Вызовы ручек ПРИЛОЖЕНИЯ рантайм тоже показывает — он же их зовёт. Но передаём их наружу
    # не мы из его шагов, а зона клиентских ручек, и с другим идентификатором: своего он ей не
    # сообщает. Отдать оба значило бы показать один вызов дважды, под двумя именами.
    theirs: set[str] = set()

    def say(kind: str, **fields: Any) -> None:
        relay.put(frame(kind, **fields))

    def called(call: str, tool: str, arguments: Any) -> None:
        """Три кадра одного вызова. Одинаковы для наших зон и для ручек приложения — снаружи
        разницы нет и быть не должно."""
        say("TOOL_CALL_START", toolCallId=call, toolCallName=tool)
        say(
            "TOOL_CALL_ARGS",
            toolCallId=call,
            delta=json.dumps(arguments or {}, ensure_ascii=False),
        )
        say("TOOL_CALL_END", toolCallId=call)

    say("RUN_STARTED", threadId=envelope.threadId, runId=envelope.runId)
    try:
        while True:
            event = await queue.get()
            kind = str(event.get("event"))

            if kind == "client-call":
                # Ручка приложения: агент позвал, исполнять будет тот, кто слушает.
                called(
                    str(event.get("call") or ""),
                    str(event.get("tool") or ""),
                    event.get("arguments"),
                )
                continue

            if kind == "client-result":
                # Приложение принесло результат. Возвращаем его же кадром протокола: у клиента
                # свой учёт вызовов, и вызов без результата остался бы в нём незакрытым.
                say(
                    "TOOL_CALL_RESULT",
                    messageId=reply_id,
                    toolCallId=str(event.get("call") or ""),
                    content=str(event.get("content") or ""),
                    role="tool",
                )
                continue

            if kind == "run-step":
                step = str(event.get("kind") or "")
                tool = event.get("tool")

                if step == "using" and tool:
                    if str(tool).startswith(CLIENT_PREFIX):
                        # Свой же вызов, пришедший вторым путём. Имя рантайма запоминаем, чтобы
                        # так же пропустить его результат: у результата имени ручки нет.
                        if event.get("call"):
                            theirs.add(str(event["call"]))
                        continue

                    calls += 1
                    # Идентификатор называет рантайм — тот же, по которому он потом пришлёт
                    # результат. Свой счётчик остаётся запасным: у старого сайдкара его нет.
                    called(
                        str(event.get("call") or f"{envelope.runId}-{calls}"),
                        str(tool),
                        event.get("arguments"),
                    )
                    continue

                if step == "result":
                    if str(event.get("call") or "") in theirs:
                        continue
                    # Идентификатор вызова здесь ЧУЖОЙ — его дал рантайм. Своей нумерацией его не
                    # подменить: снаружи по нему связывают результат с просьбой, а два разных
                    # счёта не сойдутся.
                    say(
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
                    say(
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
                    say(
                        "RUN_ERROR",
                        message=str(event.get("means") or refusal),
                        code=str(refusal),
                    )
                    return

                reply = str(event.get("reply") or "")
                if reply:
                    say("TEXT_MESSAGE_START", messageId=reply_id, role="assistant")
                    say("TEXT_MESSAGE_CONTENT", messageId=reply_id, delta=reply)
                    say("TEXT_MESSAGE_END", messageId=reply_id)

                say("RUN_FINISHED", outcome="success", result=reply)
                return
    finally:
        runner.unsubscribe(envelope.threadId, queue)
        relay.close()


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

    # Пока в потоке висит неотвеченная ручка приложения, новый ход начинать НЕЛЬЗЯ. Агент в
    # этот момент застрял посреди прежнего хода, внутри вызова, и второй ход встал бы в очередь
    # за ним — то есть молча повис бы до конца срока ожидания.
    #
    # Отбивается словами, а не тишиной: сюда попадают ровно тогда, когда результат ручки уехал
    # не той дорогой (клиентские библиотеки склонны продолжать разговор новым прогоном), и
    # человек на той стороне должен узнать причину сразу, а не через две минуты пустоты.
    awaiting = desk.pending_of(envelope.threadId)
    if awaiting:
        raise HTTPException(
            status_code=409,
            detail=(
                f"поток ждёт результат ручки приложения ({', '.join(sorted(awaiting))}). "
                f"Принеси его в POST /agent/{envelope.threadId}/tool/<toolCallId> — "
                f"это продолжение того же прогона, а не новый ход."
            ),
        )

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
            db_sessions(),
            session,
            catalog,
            probes,
            asked,
            envelope.runId,
            _context(envelope),
            [tool.model_dump() for tool in envelope.tools],
        )
    except service.Missing as missing:
        runner.unsubscribe(envelope.threadId, queue)
        raise HTTPException(status_code=409, detail=missing.refusal.means) from missing
    except Exception:
        runner.unsubscribe(envelope.threadId, queue)
        raise

    # Пересказчик заводится ЗДЕСЬ и живёт отдельной задачей: оборванный ответ больше не оставляет
    # прогон без переводчика — тот продолжает складывать кадры, и вернувшийся их дочитает.
    relay = relays.open(envelope.threadId, envelope.runId)
    translating = asyncio.create_task(
        _translate(envelope, f"msg-{envelope.runId}", queue, relay)
    )
    # Ссылка держится до конца: задача без ссылок может быть убрана сборщиком мусора посреди
    # работы, и прогон остался бы без пересказа — редко и невоспроизводимо.
    _translating.add(translating)
    translating.add_done_callback(_translating.discard)

    return EventSourceResponse(_frames(relay))


class Executed(BaseModel):
    """Результат ручки, исполненной приложением у себя."""

    content: str = ""
    """Что вернула ручка. Текстом: агент читает его так же, как ответ любой другой ручки."""

    failed: bool = False
    """Ручка отказала. Отказ обязан доехать до агента отказом, иначе он сочтёт действие
    выполненным и скажет об этом человеку."""


@router.post("/agent/{thread_id}/tool/{call_id}")
async def executed(
    thread_id: str, call_id: str, body: Executed, caller: Caller, db: CurrentDb
) -> dict[str, bool]:
    """Принести результат ручки, которую агент позвал у приложения.

    Отдельным запросом, а не через поток событий: поток идёт в одну сторону, и спросить по нему
    нельзя. Прогон при этом ОДИН — этот запрос не начинает новый ход, он лишь отвечает на вопрос
    внутри уже идущего.
    """
    session = await service.by_id(db, thread_id, caller.owner_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"потока {thread_id!r} нет")

    # Кадр уходит ДО того, как агент получит ответ: у клиента свой учёт вызовов, и закрыть его
    # он должен раньше, чем придут следующие слова агента.
    runner.tell(
        thread_id,
        {"event": "client-result", "call": call_id, "content": body.content, "failed": body.failed},
    )

    if not desk.answer(thread_id, call_id, body.content, body.failed):
        # Никто не ждёт: срок вышел, ответ уже приносили, или названо не то. Молчаливое согласие
        # оставило бы приложение в уверенности, что результат дошёл до агента.
        raise HTTPException(
            status_code=404,
            detail=f"вызова {call_id!r} никто не ждёт: срок вышел или ответ уже приносили",
        )

    return {"delivered": True}


_translating: set[asyncio.Task[None]] = set()


async def _frames(relay: Relay, last_id: int = 0) -> AsyncIterator[dict[str, str]]:
    """Кадры пересказчика в том виде, в каком их ждёт SSE.

    Номер кадра едет полем `id` — штатной механикой протокола событий, а не своей выдумкой: по
    нему вернувшийся называет место, с которого продолжать.
    """
    async for number, body in relay.follow(last_id):
        yield {"id": str(number), "data": json.dumps(body, ensure_ascii=False)}


def _last_seen(header: str | None) -> int:
    """С какого места продолжать. Непонятное значение — то же, что и его отсутствие: начать
    сначала честнее, чем угадать середину."""
    try:
        return max(0, int((header or "").strip()))
    except ValueError:
        return 0


@router.get("/agent/{thread_id}/runs/{run_id}/events")
async def events(
    thread_id: str,
    run_id: str,
    caller: Caller,
    db: CurrentDb,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> EventSourceResponse:
    """Дочитать прогон, соединение с которым оборвалось.

    Отдельной ручкой и методом GET: переподключение — это не новый ход, и делать его запросом с
    репликой значило бы врать глаголом. Место, с которого продолжать, называется заголовком
    `Last-Event-ID` — тем самым, что придуман для этого протоколом событий.

    Память коротка и живёт, пока живёт прогон (плюс несколько минут). Прогона нет в памяти —
    говорим об этом словами: итог последнего хода лежит в слоте потока, и достать его оттуда
    честнее, чем выдать пустой поток за дочитанный.
    """
    session = await service.by_id(db, thread_id, caller.owner_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"потока {thread_id!r} нет")

    relay = relays.find(thread_id, run_id)
    if relay is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"прогона {run_id!r} нет в памяти: он давно кончился или сервис перезапускался. "
                f"Итог последнего хода — в слоте потока."
            ),
        )

    return EventSourceResponse(_frames(relay, _last_seen(last_event_id)))


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
        stopped = await runner.cancel(db_sessions(), thread_id, r.id) or stopped

    return {"stopped": stopped}
