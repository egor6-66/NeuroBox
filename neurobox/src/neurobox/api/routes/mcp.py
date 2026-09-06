"""Реестр MCP по HTTP: что серверы дают и когда их спрашивали в последний раз."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from neurobox.api.deps import CurrentCatalog, CurrentRegistry
from neurobox.mcp.probe import Called, Probe, call_tool
from neurobox.model.entities import ServerSeed

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/servers")
def servers(registry: CurrentRegistry) -> list[Probe]:
    """Последнее, что известно о серверах. Пусто — значит опроса ещё не было."""
    return registry.known()


@router.post("/probe")
async def probe_all(catalog: CurrentCatalog, registry: CurrentRegistry) -> list[Probe]:
    """Опросить все семена-серверы каталога."""
    return await registry.refresh_all(list(catalog.seeds.values()))


@router.post("/servers/{seed}/probe")
async def probe_one(seed: str, catalog: CurrentCatalog, registry: CurrentRegistry) -> Probe:
    found = catalog.seeds.get(seed)
    if found is None:
        raise HTTPException(status_code=404, detail=f"семени {seed!r} нет")
    if not isinstance(found, ServerSeed):
        raise HTTPException(status_code=409, detail=f"семя {seed!r} не сервер, опрашивать нечего")

    return await registry.refresh(found)


class Arguments(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.post("/servers/{seed}/tools/{tool}")
async def call(seed: str, tool: str, body: Arguments, catalog: CurrentCatalog) -> Called:
    """Дёрнуть инструмент руками.

    Отказ инструмента НЕ превращается в ошибку HTTP: вызов состоялся, просто ручка ответила
    отрицательно — и человек обязан увидеть, что именно она сказала.
    """
    found = catalog.seeds.get(seed)
    if found is None:
        raise HTTPException(status_code=404, detail=f"семени {seed!r} нет")
    if not isinstance(found, ServerSeed):
        raise HTTPException(status_code=409, detail=f"семя {seed!r} не сервер")

    return await call_tool(found, tool, body.arguments)
