"""Прогон потоком: ход дела виден по мере работы, а не одним ответом в конце.

Тот же запрос, что и обычный, но методом `SendStreamingMessage` и с ответом в виде потока
событий. Ждать итога всё равно приходится, но теперь между началом и концом есть что показать
человеку — иначе две минуты он смотрит в пустоту и не знает, жив ли агент.
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import BaseModel

from neurobox.a2a.client import PROTOCOL_VERSION, Answer, text_of, usage_of
from neurobox.model.refusal import Refusal, RefusalName


class Step(BaseModel):
    """Один шаг прогона — то, что показывают человеку, пока он ждёт."""

    kind: str
    """Род шага, как его назвал агент: подключение, реплика, вызов инструмента."""

    text: str
    task_id: str | None = None


async def send(
    base_url: str,
    prompt: str,
    *,
    metadata: dict[str, Any] | None = None,
    context_id: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 600.0,
) -> AsyncIterator[Step | Answer]:
    """Поставить задачу и отдавать шаги по мере их прихода, последним — итог.

    Шаги и итог идут одним потоком намеренно: у вызывающего один цикл вместо двух путей, и
    невозможно случайно обработать итог, забыв про шаги.
    """
    message: dict[str, Any] = {
        "role": "ROLE_USER",
        "messageId": str(uuid.uuid4()),
        "parts": [{"text": prompt}],
        "metadata": metadata or {},
    }
    if context_id:
        message["contextId"] = context_id

    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendStreamingMessage",
        "params": {"message": message},
    }
    wire = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "A2A-Version": PROTOCOL_VERSION,
        **(headers or {}),
    }

    final: Answer | None = None
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as http:
            async with http.stream("POST", base_url, json=body, headers=wire) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = json.loads(line[5:].strip())
                    for item in _read(payload, base_url):
                        if isinstance(item, Answer):
                            final = item
                        else:
                            yield item
    except Exception as error:  # noqa: BLE001 — сеть и чужой сервис
        yield Answer(
            ok=False,
            refusals=[
                Refusal(
                    name=RefusalName.AGENT_SILENT,
                    means=f"агент не ответил: {type(error).__name__}: {error}",
                    where=base_url,
                )
            ],
        )
        return

    if final is None:
        # Поток кончился без итогового состояния — агент оборвался молча. Молчание надо
        # назвать, иначе прогон навсегда останется в «работает».
        yield Answer(
            ok=False,
            refusals=[
                Refusal(
                    name=RefusalName.AGENT_SILENT,
                    means="поток агента кончился без итогового состояния",
                    where=base_url,
                )
            ],
        )
        return

    yield final


def _read(payload: dict[str, Any], base_url: str) -> list[Step | Answer]:
    """Перевести одно событие протокола в шаг или итог."""
    if "error" in payload:
        detail = payload["error"]
        return [
            Answer(
                ok=False,
                refusals=[
                    Refusal(
                        name=RefusalName.AGENT_REFUSED,
                        means=f"агент отказал: {detail.get('message')} (код {detail.get('code')})",
                        where=base_url,
                    )
                ],
            )
        ]

    result = payload.get("result") or {}
    update = result.get("statusUpdate") or result.get("status_update")
    task = result.get("task")

    if update:
        status = update.get("status") or {}
        state = status.get("state")
        reply = status.get("message") or {}
        text = text_of(reply.get("parts"))

        if state == "TASK_STATE_WORKING":
            kind = str((update.get("metadata") or {}).get("step") or "шаг")
            return [Step(kind=kind, text=text, task_id=update.get("taskId"))] if text else []

        if state in ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED"):
            return [_final(state, text, reply, update.get("taskId"), base_url)]

    if task:
        status = task.get("status") or {}
        state = status.get("state")
        if state in ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED"):
            reply = status.get("message") or {}
            return [
                _final(state, text_of(reply.get("parts")), reply, task.get("id"), base_url)
            ]

    return []


def _final(
    state: str, text: str, reply: dict[str, Any], task_id: str | None, base_url: str
) -> Answer:
    usage = usage_of(reply)
    if state == "TASK_STATE_FAILED":
        return Answer(
            ok=False,
            task_id=task_id,
            state=state,
            text=text,
            usage=usage,
            refusals=[
                Refusal(
                    name=RefusalName.RUN_FAILED,
                    means=text or "агент завершил задачу отказом без объяснения",
                    where=base_url,
                )
            ],
        )
    return Answer(ok=True, task_id=task_id, state=state, text=text, usage=usage)
