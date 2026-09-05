"""Сборка HTTP-поверхности из маршрутов.

Один список — единственное место, где видно, что сервис вообще умеет по HTTP.
"""

from fastapi import APIRouter

from neurobox.api.routes import health

api_router = APIRouter()
api_router.include_router(health.router)
