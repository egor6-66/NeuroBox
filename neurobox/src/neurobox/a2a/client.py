"""Разговор с агентом по A2A.

Прямые запросы, а не официальный SDK: питоновский SDK версии 1.x протобуфный и тянет за собой
заметно больше, чем нужно для «поставить задачу и дождаться ответа». Форма запроса при этом
проверена живьём на настоящем агенте. SDK встанет сюда, когда дойдём до потока событий и
отмены — там он окупается, и менять придётся только этот модуль.

Три вещи, которые выяснились на живом агенте и без которых ничего не работает:
версия объявляется заголовком `A2A-Version`, иначе сервер считает нас старой версией;
имена методов версии 1.0 — `SendMessage`, а не `message/send`;
текстовая часть сообщения на проводе выглядит как `{"text": ...}`.
"""

import uuid
from typing import Any

import httpx
from pydantic import BaseModel, Field

from neurobox.model.refusal import Refusal, RefusalName

PROTOCOL_VERSION = "1.0"
CARD_PATH = ".well-known/agent-card.json"


class Skill(BaseModel):
    id: str
    name: str | None = None
    description: str | None = None


class Card(BaseModel):
    """Визитка агента — то, что он сам о себе заявляет.

    Читается у агента, а не описывается у нас: описание на нашей стороне разъехалось бы с ним
    при первом же обновлении агента, и никто бы этого не заметил.
    """

    name: str
    description: str | None = None
    version: str | None = None
    skills: list[Skill] = Field(default_factory=list)
    streaming: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    """Во что обошёлся прогон — так, как его посчитал сам агент.

    Кэш-токены отдельно: на коротком вопросе их бывает на порядок больше обычных, и учёт без
    них показывал бы копейки там, где потрачено ощутимо. Незаявленное остаётся пустым, а не
    изображает ноль — «бесплатно» и «не сказали» это разные вещи.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cache_read_tokens: int | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None


def usage_of(message: dict[str, Any]) -> Usage | None:
    raw = (message.get("metadata") or {}).get("usage")
    if not isinstance(raw, dict):
        return None
    return Usage(
        input_tokens=raw.get("inputTokens"),
        output_tokens=raw.get("outputTokens"),
        cache_creation_tokens=raw.get("cacheCreationTokens"),
        cache_read_tokens=raw.get("cacheReadTokens"),
        cost_usd=raw.get("costUsd"),
        duration_ms=raw.get("durationMs"),
    )


class Answer(BaseModel):
    """Чем кончился прогон."""

    ok: bool
    task_id: str | None = None
    context_id: str | None = None
    state: str | None = None
    text: str = ""
    usage: Usage | None = None
    refusals: list[Refusal] = Field(default_factory=list)


def text_of(parts: list[dict[str, Any]] | None) -> str:
    chunks = [str(p["text"]) for p in (parts or []) if isinstance(p.get("text"), str)]
    return "\n".join(chunks).strip()


def _silent(where: str, means: str) -> Refusal:
    return Refusal(name=RefusalName.AGENT_SILENT, means=means, where=where)


def _explain(error: Exception) -> str:
    return f"{type(error).__name__}: {error}".strip()


def card_url(base: str) -> str:
    return f"{base.rstrip('/')}/{CARD_PATH}"


async def read_card(base_url: str, timeout: float = 15.0) -> tuple[Card | None, list[Refusal]]:
    """Прочитать визитку. Недоступный агент — названный отказ, а не исключение."""
    url = card_url(base_url)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as http:
            response = await http.get(url)
            response.raise_for_status()
            raw = response.json()
    except Exception as error:  # noqa: BLE001 — агент снаружи, падать он вправе как угодно
        return None, [_silent(url, f"визитка не прочиталась: {_explain(error)}")]

    if not isinstance(raw, dict):
        return None, [_silent(url, "визитка не объект")]

    capabilities = raw.get("capabilities") or {}
    skills = [
        Skill(id=str(s.get("id")), name=s.get("name"), description=s.get("description"))
        for s in (raw.get("skills") or [])
        if isinstance(s, dict) and s.get("id")
    ]
    return (
        Card(
            name=str(raw.get("name") or "без имени"),
            description=raw.get("description"),
            version=raw.get("version"),
            skills=skills,
            streaming=bool(capabilities.get("streaming")),
            raw=raw,
        ),
        [],
    )


async def send(
    base_url: str,
    prompt: str,
    *,
    metadata: dict[str, Any] | None = None,
    context_id: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 600.0,
) -> Answer:
    """Поставить задачу и дождаться ответа.

    `context_id` продолжает начатый разговор: у протокола это тот же контекст, который у нас
    зовётся сессией, поэтому история держится на его стороне, а не пересобирается нами.
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
        "method": "SendMessage",
        "params": {"message": message},
    }
    wire = {
        "Content-Type": "application/json",
        "A2A-Version": PROTOCOL_VERSION,
        **(headers or {}),
    }

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as http:
            response = await http.post(base_url, json=body, headers=wire)
            response.raise_for_status()
            raw = response.json()
    except Exception as error:  # noqa: BLE001 — сеть и чужой сервис
        return Answer(ok=False, refusals=[_silent(base_url, f"агент не ответил: {_explain(error)}")])

    if "error" in raw:
        detail = raw["error"]
        return Answer(
            ok=False,
            refusals=[
                Refusal(
                    name=RefusalName.AGENT_REFUSED,
                    means=f"агент отказал: {detail.get('message')} (код {detail.get('code')})",
                    where=base_url,
                )
            ],
        )

    task = (raw.get("result") or {}).get("task") or {}
    status = task.get("status") or {}
    state = status.get("state")
    reply = status.get("message") or {}
    text = text_of(reply.get("parts"))
    usage = usage_of(reply)

    # Провалившаяся задача — законное состояние протокола, а не сбой связи: причину агент
    # положил в текст, и она обязана доехать до человека, а не превратиться в пустой отказ.
    if state == "TASK_STATE_FAILED":
        return Answer(
            ok=False,
            task_id=task.get("id"),
            context_id=task.get("contextId"),
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

    return Answer(
        ok=True,
        task_id=task.get("id"),
        context_id=task.get("contextId"),
        state=state,
        text=text,
        usage=usage,
    )
