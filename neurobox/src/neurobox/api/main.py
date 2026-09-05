"""Сборка HTTP-поверхности из маршрутов.

Один список — единственное место, где видно, что сервис вообще умеет по HTTP.
"""

from fastapi import APIRouter

from neurobox.api.routes import catalog, health, mcp

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(catalog.router)
api_router.include_router(mcp.router)
