"""Логи, по которым можно найти конкретный запрос.

Тридцатисекундный прогон без записей — чёрный ящик: видно, что было плохо, и не видно, где.
Поэтому у каждой записи есть идентификатор запроса, и по нему собирается вся его история,
включая работу, которая продолжилась уже после ответа клиенту.

Формат зависит от окружения: в разработке человек читает глазами, в остальных случаях записи
разбирает машина. Заводить два разных набора полей ради этого не нужно — меняется только
оформление.
"""

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

from neurobox.core.config import settings

request_id: ContextVar[str] = ContextVar("request_id", default="—")
"""Идентификатор текущего запроса. Контекстная переменная, а не аргумент: иначе его пришлось бы
протаскивать через каждый вызов, и он потерялся бы на первом же слое, где о нём забыли."""

_OWN = (
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "taskName",
    "message",
    "asctime",
)


def _extras(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in _OWN}


class Machine(logging.Formatter):
    """Запись объектом: её разбирает сборщик логов, а не человек глазами."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "at": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "request": request_id.get(),
            "message": record.getMessage(),
            **_extras(record),
        }
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class Human(logging.Formatter):
    """Одна строка на запись, читаемая глазами. Только для разработки."""

    def format(self, record: logging.LogRecord) -> str:
        extras = _extras(record)
        tail = " ".join(f"{k}={v}" for k, v in extras.items() if v is not None)
        line = (
            f"{self.formatTime(record, '%H:%M:%S')} "
            f"{record.levelname[:4].lower():<5} "
            f"[{request_id.get()[:8]}] {record.getMessage()}"
        )
        if tail:
            line = f"{line}  {tail}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


OURS = "neurobox"
"""Метка нашего обработчика: по ней он отличается от чужих."""


def setup() -> None:
    """Настроить вывод один раз при старте.

    Заменяется ТОЛЬКО наш обработчик. Снести все — приём грубый и ломающий: чужие обработчики
    ставят и тесты, и то, что запускает сервис снаружи, и молча выкидывать их значит забирать у
    людей их же записи.

    Заодно глушится собственный журнал доступа uvicorn: свой у нас точнее (в нём есть
    идентификатор запроса и время работы), а две записи об одном запросе только мешают искать.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(Human() if settings.environment == "local" else Machine())
    handler.set_name(OURS)

    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if h.get_name() != OURS]
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("uvicorn.error").propagate = True
