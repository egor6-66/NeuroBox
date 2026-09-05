"""Журнал обращений: кто пришёл, чем кончилось и сколько заняло."""

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from neurobox.core import logs

HEADER = "X-Request-ID"

log = logging.getLogger("neurobox.access")


class Access(BaseHTTPMiddleware):
    """Один запрос — одна запись, с идентификатором и временем работы.

    Идентификатор берётся из заголовка, если он пришёл: сквозной след через несколько сервисов
    важнее нашей аккуратности в его выдаче. Не пришёл — заводим свой.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(HEADER, "").strip()
        current = incoming or uuid.uuid4().hex[:12]
        token = logs.request_id.set(current)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Запись до того, как исключение уйдёт наверх: иначе о самом важном запросе не
            # останется ни строки, и искать придётся по чужой трассировке.
            log.exception(
                "запрос упал",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "ms": round((time.perf_counter() - started) * 1000),
                },
            )
            logs.request_id.reset(token)
            raise

        spent = round((time.perf_counter() - started) * 1000)
        log.info(
            "запрос",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "ms": spent,
            },
        )
        response.headers[HEADER] = current
        logs.request_id.reset(token)
        return response
