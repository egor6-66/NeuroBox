"""Прогон, пересказанный кадрами протокола, — с короткой памятью на время самого прогона.

Раньше перевод жил внутри HTTP-ответа: оборвалось соединение — переводить стало некому, и
события уходили в пустоту, хотя прогон продолжался и деньги тратились. Человек в метро или с
заснувшим ноутбуком терял не связь, а работу.

Поэтому пересказчик отвязан от соединения. Он живёт столько же, сколько прогон, складывает кадры
в память и раздаёт их всем, кто слушает. Вернулся человек — дочитал пропущенное и поехал дальше.

> [!NOTE]
> Это НЕ история разговора. Память здесь — кадры одного хода, она не переживает его дольше
> короткой отсрочки и никогда не ложится в базу. Разговор по-прежнему принадлежит тому, кто его
> ведёт; здесь лежит недочитанное, а не прошлое.

Память ограничена, и это названо, а не спрятано: длинный ход вытеснит своё же начало. Вернувшийся
узнает о разрыве отдельным кадром, а не получит склейку, в которой чего-то молча нет.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("neurobox.relay")

FRAMES_KEPT = 2000
"""Сколько кадров держим на прогон. Дальше вытесняется самое старое."""

BYTES_KEPT = 512 * 1024
"""И сколько это в байтах — кадр кадру рознь: аргументы ручки бывают длиннее всего остального."""

LINGER_SECONDS = 300.0
"""Сколько пересказчик живёт после конца прогона.

Не ноль: связь чаще всего рвётся у тех, кто ждал ответа, и вернувшийся через минуту должен
получить итог, а не пустоту. Не вечность: это память, а не хранилище.
"""

RELAYS_KEPT = 200
"""Предел на число пересказчиков в памяти. Переполнение уносит самые старые завершённые."""


def frame(kind: str, **fields: Any) -> dict[str, Any]:
    """Кадр протокола. Тип лежит ВНУТРИ данных, а не в имени события SSE.

    Так велит протокол, и это не мелочь: клиент разбирает один поток однородных объектов и не
    обязан подписываться на каждое имя отдельно.
    """
    return {"type": kind, **fields}


@dataclass
class Relay:
    """Один прогон: его кадры, его слушатели, его конец."""

    thread: str
    run: str

    kept: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    """Кадры с их номерами — то, что сможет дочитать вернувшийся."""

    issued: int = 0
    """Сколько кадров выпущено всего. Номер — он же `id` события SSE."""

    dropped: int = 0
    """Сколько вытеснено из памяти. Ноль — значит вернувшийся получит всё без дыр."""

    size: int = 0
    listeners: set[asyncio.Queue[tuple[int, dict[str, Any]] | None]] = field(default_factory=set)
    done: bool = False
    closed_at: float | None = None

    def put(self, body: dict[str, Any]) -> None:
        """Выпустить кадр: пронумеровать, запомнить, раздать."""
        self.issued += 1
        item = (self.issued, body)

        self.kept.append(item)
        self.size += len(json.dumps(body, ensure_ascii=False))
        while self.kept and (len(self.kept) > FRAMES_KEPT or self.size > BYTES_KEPT):
            _, gone = self.kept.pop(0)
            self.size -= len(json.dumps(gone, ensure_ascii=False))
            self.dropped += 1

        for queue in self.listeners:
            queue.put_nowait(item)

    def close(self) -> None:
        """Прогон кончился. Слушателям — конец потока, памяти — отсрочка."""
        if self.done:
            return

        self.done = True
        self.closed_at = time.monotonic()
        for queue in self.listeners:
            queue.put_nowait(None)

    def since(self, last_id: int) -> tuple[list[tuple[int, dict[str, Any]]], bool]:
        """Что вернувшийся пропустил и была ли дыра.

        Дыра — это когда просят старее, чем у нас осталось. Честно сказать о ней важнее, чем
        отдать склейку: человек по ней решает, доверять ли тому, что видит на экране.
        """
        missed = [item for item in self.kept if item[0] > last_id]
        earliest = self.kept[0][0] if self.kept else self.issued + 1
        gap = last_id + 1 < earliest
        return missed, gap

    async def follow(self, last_id: int = 0) -> AsyncIterator[tuple[int, dict[str, Any]]]:
        """Читать прогон с названного места: сначала пропущенное, потом живое.

        Каждый кадр приезжает СО СВОИМ номером, а не с текущим счётчиком пересказчика: номер
        едет наружу как место, с которого продолжать, и назови мы чужой — вернувшийся попросил
        бы продолжить не оттуда, где остановился.

        Подписка занимается ДО выдачи пропущенного: подпишись мы после, кадры, выпущенные между
        чтением памяти и подпиской, провалились бы в щель — редко, невоспроизводимо и молча.
        """
        queue: asyncio.Queue[tuple[int, dict[str, Any]] | None] = asyncio.Queue()
        self.listeners.add(queue)
        try:
            missed, gap = self.since(last_id)
            if gap:
                # Отдельным кадром, а не молчанием: недосказанность здесь выглядела бы как
                # «агент ничего не делал», и человек сделал бы неверный вывод о работе.
                yield last_id, frame(
                    "CUSTOM",
                    name="frames-lost",
                    value={
                        "since": last_id,
                        "dropped": self.dropped,
                        "means": "часть событий вытеснена из памяти прогона и уже не восстановится",
                    },
                )

            seen = last_id
            for number, body in missed:
                seen = number
                yield number, body

            if self.done:
                return

            if last_id:
                # Граница живого — только вернувшемуся: по ней он понимает, что догнал и дальше
                # всё приходит вовремя. Пришедшему впервые догонять нечего, и лишний кадр в
                # обычном потоке был бы отступлением от протокола на ровном месте.
                yield seen, frame("CUSTOM", name="live", value={"since": seen})

            while True:
                item = await queue.get()
                if item is None:
                    return
                number, body = item
                if number <= seen:
                    # Кадр из памяти, уже отданный выше: подписка была раньше чтения, и часть
                    # кадров законно приходит обоими путями.
                    continue
                seen = number
                yield number, body
        finally:
            self.listeners.discard(queue)


class Relays:
    """Пересказчики живых прогонов. Живут в памяти процесса, как и сами прогоны."""

    def __init__(self) -> None:
        self._by_run: dict[tuple[str, str], Relay] = {}

    def open(self, thread: str, run: str) -> Relay:
        self._sweep()
        relay = Relay(thread=thread, run=run)
        self._by_run[(thread, run)] = relay
        return relay

    def find(self, thread: str, run: str) -> Relay | None:
        return self._by_run.get((thread, run))

    def of_thread(self, thread: str) -> list[Relay]:
        """Прогоны потока, свежие впереди: вернувшийся часто не помнит, какой ход он слушал."""
        mine = [r for (t, _), r in self._by_run.items() if t == thread]
        return sorted(mine, key=lambda r: r.closed_at or float("inf"), reverse=True)

    def _sweep(self) -> None:
        """Убрать отжившее. Живой прогон не трогается никогда — он ещё может заговорить."""
        now = time.monotonic()
        stale = [
            key
            for key, relay in self._by_run.items()
            if relay.done and relay.closed_at is not None and now - relay.closed_at > LINGER_SECONDS
        ]
        for key in stale:
            del self._by_run[key]

        if len(self._by_run) <= RELAYS_KEPT:
            return

        # Переполнение: уносим завершённые, начиная с самых старых. Живые остаются — потерять
        # пересказчика работающего прогона значит потерять сам прогон для всех, кто его слушает.
        finished = sorted(
            ((key, r) for key, r in self._by_run.items() if r.done),
            key=lambda pair: pair[1].closed_at or 0.0,
        )
        for key, _ in finished[: len(self._by_run) - RELAYS_KEPT]:
            del self._by_run[key]


relays = Relays()
"""Один набор на процесс — как и реестр прогонов, которому он служит."""
