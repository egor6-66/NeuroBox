"""Сборка HTTP-поверхности из маршрутов.

Один список — единственное место, где видно, что сервис вообще умеет по HTTP.
"""

from fastapi import APIRouter, Depends

from neurobox.api.identity import who
from neurobox.api.routes import agent, agents, catalog, health, mcp

api_router = APIRouter()

# Состояние спрашивают снаружи, не заходя внутрь: закрыть его значило бы, что оркестратор
# не может узнать даже того, что сервис поднялся.
api_router.include_router(health.router)
# Проверка входа вешается на РОУТЕР, а не на каждую ручку: забытая ручка при втором способе
# оказалась бы открытой, и заметили бы это не мы.
closed = APIRouter(dependencies=[Depends(who)])
closed.include_router(catalog.router)
closed.include_router(mcp.router)
closed.include_router(agents.router)
closed.include_router(agent.router)

api_router.include_router(closed)
