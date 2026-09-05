"""Что известно об агентах. Зеркало реестра MCP-серверов, только уровнем выше.

Там опрашивается сервер и запоминается перечень тулзов, здесь опрашивается агент и запоминается
визитка. Приём один: описание вычитывается у источника, а не пишется у нас.
"""

import asyncio
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from neurobox.a2a.client import Card, read_card
from neurobox.model.entities import Agent
from neurobox.model.refusal import Refusal


class Known(BaseModel):
    """Последнее, что агент о себе сказал."""

    agent: str
    at: datetime
    ok: bool
    card: Card | None = None
    refusals: list[Refusal] = Field(default_factory=list)


class Registry:
    def __init__(self) -> None:
        self._known: dict[str, Known] = {}

    def all(self) -> list[Known]:
        return list(self._known.values())

    def get(self, agent: str) -> Known | None:
        return self._known.get(agent)

    def remember(self, known: Known) -> Known:
        self._known[known.agent] = known
        return known

    async def refresh(self, agent: Agent) -> Known:
        at = datetime.now(UTC)

        # Агент, у которого уже не сложилось чтение (нет токена), не опрашивается: запрос без
        # подставленного токена увёл бы причину в сторону от настоящей.
        if agent.refusals:
            return self.remember(
                Known(agent=agent.name, at=at, ok=False, refusals=list(agent.refusals))
            )

        card, refusals = await read_card(agent.url)
        return self.remember(
            Known(agent=agent.name, at=at, ok=card is not None, card=card, refusals=refusals)
        )

    async def refresh_all(self, agents: list[Agent]) -> list[Known]:
        """Опросить всех разом: недоступный агент не должен задерживать остальных."""
        return list(await asyncio.gather(*(self.refresh(a) for a in agents)))


registry = Registry()
"""Один на процесс. Как и у серверов, постоянное место — база, форма обращения не изменится."""
