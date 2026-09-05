"""Реестр агентов по HTTP: кто объявлен и что о себе говорит."""

from fastapi import APIRouter, HTTPException

from neurobox.a2a.registry import Known
from neurobox.api.deps import CurrentAgents, CurrentCatalog

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
def listing(agents: CurrentAgents) -> list[Known]:
    """Последнее, что известно об агентах. Пусто — значит опроса ещё не было."""
    return agents.all()


@router.post("/probe")
async def probe_all(catalog: CurrentCatalog, agents: CurrentAgents) -> list[Known]:
    return await agents.refresh_all(list(catalog.agents.values()))


@router.post("/{agent}/probe")
async def probe_one(agent: str, catalog: CurrentCatalog, agents: CurrentAgents) -> Known:
    found = catalog.agents.get(agent)
    if found is None:
        raise HTTPException(status_code=404, detail=f"агента {agent!r} нет")
    return await agents.refresh(found)
