"""Прогоны, которые не держат соединение.

Агент думает минутами. Держать всё это время открытый HTTP-запрос нельзя: прокси,
балансировщик, браузер и мобильная сеть закроют его задолго до конца, и работа умрёт вместе с
соединением. Поэтому реплика ставится в работу и сразу возвращает управление, а за ходом дела
клиент следит потоком событий.

> [!NOTE]
> Прогоны исполняются в этом процессе. Это ЗАЯВЛЕННОЕ временное состояние: очередь и отдельный
> воркер приезжают своей фазой, и меняется тогда только этот модуль — форма ручек уже такая,
> какая нужна. То, что процесс не переживает рестарт, не прячется: незавершённые прогоны при
> старте честно помечаются прерванными, а не висят в «работает» вечно.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from neurobox.a2a import client
from neurobox.db.models import Run, RunState, Session
from neurobox.mcp.probe import Probe
from neurobox.model.catalog import Catalog
from neurobox.model.refusal import RefusalName
from neurobox.sessions import service

Event = dict[str, Any]

log = logging.getLogger("neurobox.runs")


class Runner:
    """Исполняет прогоны в фоне и рассказывает о них слушателям."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._listeners: dict[str, set[asyncio.Queue[Event]]] = {}

    # --- слушатели ---------------------------------------------------------

    async def watch(self, session_id: str) -> AsyncIterator[Event]:
        """События сессии, пока их слушают.

        Отписка в `finally`: без неё очередь ушедшего клиента копила бы события навсегда, и
        каждый закрытый браузер оставлял бы после себя утечку.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._listeners.setdefault(session_id, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            listeners = self._listeners.get(session_id)
            if listeners is not None:
                listeners.discard(queue)
                if not listeners:
                    del self._listeners[session_id]

    def _tell(self, session_id: str, event: Event) -> None:
        for queue in self._listeners.get(session_id, set()):
            queue.put_nowait(event)

    def listeners_of(self, session_id: str) -> int:
        return len(self._listeners.get(session_id, set()))

    # --- исполнение --------------------------------------------------------

    def working(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    async def start(
        self,
        maker: async_sessionmaker[AsyncSession],
        session: Session,
        catalog: Catalog,
        probes: dict[str, Probe],
        text: str,
    ) -> Run:
        """Поставить реплику в работу и вернуть управление, не дожидаясь ответа.

        Запись прогона делается ЗДЕСЬ, а не в фоне: иначе ручка вернула бы идентификатор,
        которого в базе ещё нет, и клиент подписался бы на несуществующий прогон.
        """
        async with maker() as db:
            merged = await db.merge(session)
            run, agent, metadata = await service.begin(db, merged, catalog, probes, text)
            run_id, session_id, url, headers = run.id, merged.id, agent.url, agent.headers

        log.info("прогон начат", extra={"run": run_id, "session": session_id})
        self._tell(session_id, {"event": "run-started", "run": run_id})

        task = asyncio.create_task(
            self._carry(maker, run_id, session_id, url, headers, metadata, text)
        )
        self._tasks[run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(run_id, None))
        return run

    async def _carry(
        self,
        maker: async_sessionmaker[AsyncSession],
        run_id: str,
        session_id: str,
        url: str,
        headers: dict[str, str],
        metadata: dict[str, object],
        text: str,
    ) -> None:
        started = time.perf_counter()

        # Отмена НЕ обрабатывается здесь намеренно: у отменённой задачи собственные `await`
        # уже не отрабатывают, и запись в базу из этого места молча не доезжала бы. Закрывает
        # прогон тот, кто отменяет, — он не отменён.
        answer = await client.send(
            url, text, metadata=metadata, context_id=session_id, headers=headers or None
        )

        async with maker() as db:
            run = await service.run_by_id(db, run_id)
            if run is None:
                return
            done = await service.finish(db, run, answer)
            # Запись о конце прогона делается здесь, потому что запрос давно ответил: связать
            # её с ним можно только по идентификатору, который тянется контекстом.
            log.info(
                "прогон завершён",
                extra={
                    "run": run_id,
                    "session": session_id,
                    "state": done.state.value,
                    "refusal": done.refusal,
                    "ms": round((time.perf_counter() - started) * 1000),
                    "cost_micros": done.cost_micros,
                },
            )
            self._tell(
                session_id,
                {
                    "event": "run-finished",
                    "run": run_id,
                    "state": done.state.value,
                    "reply": answer.text,
                    "refusal": done.refusal,
                    "means": done.means,
                },
            )

    async def cancel(self, maker: async_sessionmaker[AsyncSession], run_id: str) -> bool:
        """Прервать прогон. Возвращает, было ли что прерывать."""
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False

        task.cancel()
        # Ждём, пока задача действительно свернётся: иначе ручка отвечает «отменено», а прогон
        # ещё пишет в базу, и следующий запрос видит состояние, которого уже не должно быть.
        with contextlib.suppress(asyncio.CancelledError):
            await task

        session_id = ""
        async with maker() as db:
            run = await service.run_by_id(db, run_id)
            if run is not None and run.state is RunState.WORKING:
                session_id = run.session_id
                await service.cancelled(db, run, "прогон отменён")

        if session_id:
            log.info("прогон отменён", extra={"run": run_id, "session": session_id})
            self._tell(session_id, {"event": "run-canceled", "run": run_id})
        return True


async def reconcile(maker: async_sessionmaker[AsyncSession]) -> int:
    """Закрыть прогоны, оборванные рестартом.

    Прогон в состоянии «работает» сразу после старта процесса означает, что исполнявший его
    процесс умер. Никто его не продолжит, и оставить запись как есть значило бы вечно висящий
    прогон, о котором человек не узнает правды.
    """
    async with maker() as db:
        found = await db.execute(select(Run.id).where(Run.state == RunState.WORKING))
        stale = len(list(found.scalars().all()))
        if not stale:
            return 0

        await db.execute(
            update(Run)
            .where(Run.state == RunState.WORKING)
            .values(
                state=RunState.FAILED,
                refusal=RefusalName.INTERRUPTED.value,
                means="прогон оборван рестартом сервиса и продолжен не будет",
                finished_at=datetime.now(UTC),
            )
        )
        await db.commit()
        log.warning("прогоны оборваны рестартом", extra={"count": stale})
        return stale


runner = Runner()
"""Один на процесс — как и реестры. Заменится очередью, форма обращения не изменится."""
