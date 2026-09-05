"""Реестр MCP по HTTP: что серверы дают и когда их спрашивали в последний раз."""

from fastapi import APIRouter, HTTPException

from neurobox.api.deps import CurrentCatalog, CurrentRegistry
from neurobox.mcp.probe import Probe
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
