"""Точка входа приложения."""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy.exc import SQLAlchemyError

from neurobox.api.access import Access
from neurobox.api.main import api_router
from neurobox.box.registry import OWN
from neurobox.box.session import Mount
from neurobox.core import logs
from neurobox.core.config import settings
from neurobox.db.engine import dispose, sessions
from neurobox.sessions.runner import reconcile

log = logging.getLogger("neurobox")

# Наши MCP-серверы — отдельные приложения: у протокола свой транспорт, и протаскивать его через
# обычные маршруты значило бы повторять чужую работу. Собираются один раз: их жизненный цикл
# запускается ниже, и второй экземпляр остался бы без него.
_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[h.strip() for h in settings.box_hosts.split(",") if h.strip()],
)

_mounts: dict[str, Mount] = {own.name: Mount() for own in OWN}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """Прогоны, оборванные прошлым запуском, закрываются при старте.

    Иначе они остаются в состоянии «работает» навсегда: исполнявший их процесс мёртв, продолжить
    их некому, и человек видел бы вечно думающего агента.
    """
    logs.setup()

    # Недоступная база НЕ мешает сервису подняться: он обязан ответить на вопрос о готовности
    # словами, а не умереть без объяснений. Иначе человек видит упавший контейнер и не знает,
    # сломан сервис или просто не поднялась база.
    closed: int | None = None
    try:
        closed = await reconcile(sessions())
    except (SQLAlchemyError, OSError) as error:
        log.warning(
            "база недоступна при старте, оборванные прогоны не закрыты",
            extra={"means": f"{type(error).__name__}: {error}"[:300]},
        )

    log.info("сервис поднят", extra={"closed_runs": closed, "environment": settings.environment})

    # Жизненный цикл смонтированных приложений запускается ЗДЕСЬ: во вложенные приложения он
    # сам не проходит, и без этого менеджер сессий протокола остаётся неинициализированным —
    # сервер отвечает пятисотой на первый же запрос, а причина видна только в трассировке.
    async with AsyncExitStack() as stack:
        for own in OWN:
            own_app = own.build().streamable_http_app(transport_security=_security)
            await stack.enter_async_context(own_app.router.lifespan_context(own_app))
            _mounts[own.name].use(own_app)
        yield

    await dispose()


app = FastAPI(title=settings.project_name, lifespan=lifespan)

app.add_middleware(Access)
app.include_router(api_router)

for own in OWN:
    app.mount(own.path, _mounts[own.name])
