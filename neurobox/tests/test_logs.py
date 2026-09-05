"""Логи: по записи можно найти конкретный запрос, а по запросу — всю его историю."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from neurobox.api.access import HEADER
from neurobox.core import logs
from neurobox.main import app


def record(message: str = "проба", **extra: object) -> logging.LogRecord:
    made = logging.LogRecord(
        name="neurobox.проба",
        level=logging.INFO,
        pathname="проба.py",
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(made, key, value)
    return made


def test_machine_record_is_an_object_with_the_request_id() -> None:
    """Запись разбирает сборщик логов, значит она обязана быть объектом, а не строкой."""
    token = logs.request_id.set("абв123")
    try:
        line = logs.Machine().format(record("прогон начат", run="з-1"))
    finally:
        logs.request_id.reset(token)

    payload = json.loads(line)
    assert payload["message"] == "прогон начат"
    assert payload["request"] == "абв123"
    assert payload["run"] == "з-1"
    assert payload["level"] == "info"


def test_human_record_stays_one_line() -> None:
    """В разработке читает человек: перенос строки ломает беглый просмотр."""
    line = logs.Human().format(record("прогон завершён", run="з-1", ms=42))

    assert "\n" not in line
    assert "прогон завершён" in line
    assert "ms=42" in line


def test_request_id_comes_back_in_the_header() -> None:
    """Без него человек не может назвать нам запрос, о котором спрашивает."""
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.headers[HEADER]


def test_incoming_request_id_is_honoured() -> None:
    """Сквозной след через несколько сервисов важнее нашей аккуратности в выдаче имени."""
    with TestClient(app) as client:
        # Только латиница: в заголовках HTTP кириллице места нет, и настоящие следы её не несут.
        response = client.get("/health", headers={HEADER: "chuzhoy-sled"})

    assert response.headers[HEADER] == "chuzhoy-sled"


def test_access_record_carries_timing(caplog: pytest.LogCaptureFixture) -> None:
    """Запись без времени работы не отвечает на главный вопрос — почему было долго."""
    with caplog.at_level(logging.INFO, logger="neurobox.access"), TestClient(app) as client:
        client.get("/health")

    entries = [r for r in caplog.records if r.name == "neurobox.access"]
    assert entries
    # Дополнительные поля живут в словаре записи, а не среди её объявленных атрибутов:
    # обращение через точку ruff разрешает, а проверка типов справедливо не признаёт.
    last = entries[-1].__dict__
    assert last["status"] == 200
    assert isinstance(last["ms"], int)
