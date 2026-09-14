"""Переподключение: оборванное соединение не должно стоить работы.

Проверяется ровно то, ради чего пересказчик заведён: кадры копятся, пока прогон идёт, и
вернувшийся дочитывает пропущенное с названного места. И отдельно — что о потере говорят
словами, а не молчанием.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from neurobox.api import relay as relay_module
from neurobox.api.relay import Relay, Relays, frame


async def taken(
    stream: AsyncIterator[tuple[int, dict[str, Any]]], limit: int
) -> list[tuple[int, dict[str, Any]]]:
    out: list[tuple[int, dict[str, Any]]] = []
    async for item in stream:
        out.append(item)
        if len(out) >= limit:
            break
    return out


def test_frames_are_numbered_from_one() -> None:
    """Номер кадра — это место, с которого вернувшийся попросит продолжить."""
    relay = Relay(thread="п", run="х")

    relay.put(frame("RUN_STARTED"))
    relay.put(frame("TEXT_MESSAGE_CONTENT", delta="раз"))

    assert [number for number, _ in relay.kept] == [1, 2]


@pytest.mark.asyncio
async def test_returning_reader_gets_what_he_missed() -> None:
    """Соединение оборвалось посреди хода — работа продолжалась, и она не должна пропасть."""
    relay = Relay(thread="п", run="х")
    relay.put(frame("RUN_STARTED"))
    relay.put(frame("TOOL_CALL_START", toolCallId="в-1"))
    relay.put(frame("TOOL_CALL_RESULT", toolCallId="в-1", content="сохранено"))

    # Вернулся, прочитав только первый кадр.
    got = await taken(relay.follow(1), 3)

    kinds = [body["type"] for _, body in got]
    assert kinds[:2] == ["TOOL_CALL_START", "TOOL_CALL_RESULT"]
    # И граница живого — вернувшийся должен знать, что догнал.
    assert kinds[2] == "CUSTOM" and got[2][1]["name"] == "live"


@pytest.mark.asyncio
async def test_first_reader_gets_the_protocol_without_additions() -> None:
    """Пришедшему впервые догонять нечего: лишний кадр был бы отступлением от протокола."""
    relay = Relay(thread="п", run="х")
    relay.put(frame("RUN_STARTED"))
    relay.close()

    got = [body["type"] async for _, body in relay.follow(0)]

    assert got == ["RUN_STARTED"]


@pytest.mark.asyncio
async def test_live_frames_reach_a_reader_who_caught_up() -> None:
    """Догнал — и дальше читает вживую, тем же потоком."""
    relay = Relay(thread="п", run="х")
    relay.put(frame("RUN_STARTED"))

    reading = asyncio.create_task(taken(relay.follow(1), 2))
    await asyncio.sleep(0)
    relay.put(frame("RUN_FINISHED", result="готово"))

    got = await asyncio.wait_for(reading, timeout=2)

    assert [body["type"] for _, body in got] == ["CUSTOM", "RUN_FINISHED"]


@pytest.mark.asyncio
async def test_a_frame_is_not_told_twice() -> None:
    """Подписка раньше чтения памяти — иначе кадры проваливаются в щель между ними.

    Плата за это — кадр, пришедший обоими путями; показать его дважды нельзя.
    """
    relay = Relay(thread="п", run="х")
    relay.put(frame("RUN_STARTED"))

    stream = relay.follow(0)
    first = await anext(stream)
    # Кадр, уже лежавший в памяти, но пришедший ещё и очередью.
    for queue in relay.listeners:
        queue.put_nowait((1, frame("RUN_STARTED")))
    relay.put(frame("RUN_FINISHED", result=""))

    second = await asyncio.wait_for(anext(stream), timeout=2)

    assert first[1]["type"] == "RUN_STARTED"
    assert second[1]["type"] == "RUN_FINISHED"


@pytest.mark.asyncio
async def test_loss_is_told_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    """Склейка, в которой чего-то молча нет, хуже честного «часть потеряна».

    По потоку человек судит о работе агента: молчание он прочтёт как «ничего не делал».
    """
    monkeypatch.setattr(relay_module, "FRAMES_KEPT", 2)
    relay = Relay(thread="п", run="х")
    for i in range(5):
        relay.put(frame("TEXT_MESSAGE_CHUNK", delta=str(i)))

    got = await taken(relay.follow(1), 1)

    assert got[0][1]["type"] == "CUSTOM"
    assert got[0][1]["name"] == "frames-lost"
    assert got[0][1]["value"]["dropped"] == 3


def test_finished_runs_are_swept_but_live_ones_stay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Потерять пересказчика работающего прогона значит потерять прогон для всех, кто его слушает."""
    monkeypatch.setattr(relay_module, "RELAYS_KEPT", 1)
    relays = Relays()
    old = relays.open("п", "х-1")
    old.close()
    relays.open("п", "х-2")

    relays.open("п", "х-3")

    assert relays.find("п", "х-2") is not None
    assert relays.find("п", "х-3") is not None
