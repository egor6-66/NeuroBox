"""Где живут результаты опроса.

Опрос — сетевой вызов, поэтому, в отличие от чтения файлов, он не может происходить на каждый
запрос: сервер отвечает секунды, а список каталога человек открывает постоянно.

> [!NOTE]
> Хранилище пока в памяти процесса и переживает только его. Это ЗАЯВЛЕННОЕ временное состояние,
> не недосмотр: постоянное место — база, и она приезжает своей фазой. Перезапуск обнуляет
> реестр, и первый опрос после старта делается заново.
"""

import asyncio

from neurobox.mcp.probe import Probe, probe
from neurobox.model.entities import Seed, ServerSeed


class Registry:
    """Последний известный ответ каждого сервера."""

    def __init__(self) -> None:
        self._probes: dict[str, Probe] = {}

    def known(self) -> list[Probe]:
        return list(self._probes.values())

    def get(self, seed: str) -> Probe | None:
        return self._probes.get(seed)

    def remember(self, result: Probe) -> Probe:
        self._probes[result.seed] = result
        return result

    async def refresh(self, seed: ServerSeed) -> Probe:
        return self.remember(await probe(seed))

    async def refresh_all(self, seeds: list[Seed]) -> list[Probe]:
        """Опросить все семена-серверы разом.

        Параллельно, потому что медленный сервер не должен задерживать остальные — иначе один
        зависший адрес делает опрос всего реестра бесполезно долгим.
        """
        servers = [s for s in seeds if isinstance(s, ServerSeed)]
        results = await asyncio.gather(*(probe(s) for s in servers))
        return [self.remember(result) for result in results]


registry = Registry()
"""Один на процесс. Заменится хранилищем в базе — форма обращения при этом не изменится."""
