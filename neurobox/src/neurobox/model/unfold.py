"""Развёртка — во что превращается рецепт перед тем, как его получит агент.

Семя разворачивается во много: адрес — в перечень тулзов, имя знания — в текст инструкции.
Рецепт это набор семян, значит и он разворачивается. Отсюда слово.

> [!NOTE]
> «Развёртка» — НОВОЕ слово в общем словаре, а не синоним существующего. «Сборка» занята и
> значит другое (прогнанное доказательство), «рецепт» — это вход, а не результат. Развёртка —
> именно результат: то, что получилось из рецепта под конкретным паспортом, в конкретный момент
> состояния реестра.

Развёртка ничего не решает и никуда не ходит. Она складывает уже известное: тексты знаний,
адреса опрошенных серверов, вердикт сверки — и называет всё, что не вошло, и почему.
"""

from typing import Any

from pydantic import BaseModel, Field

from neurobox.mcp.probe import Probe, ToolBrief
from neurobox.model.catalog import Catalog
from neurobox.model.entities import KnowledgeSeed, Passport, Recipe, ServerSeed
from neurobox.model.fit import Verdict, check
from neurobox.model.refusal import Refusal, RefusalName


class ServerPlan(BaseModel):
    """Сервер, готовый к подключению: чем соединяться и что он даёт."""

    seed: str
    server: dict[str, Any]
    tools: list[ToolBrief] = Field(default_factory=list)


class Unfolded(BaseModel):
    recipe: str
    passport: str

    instructions: str
    """Тексты знание-семян в порядке рецепта. Порядок объявления сохраняется: человек им
    распоряжается осознанно, и перетасовка меняла бы смысл без его ведома."""

    servers: list[ServerPlan] = Field(default_factory=list)
    """Только опрошенные и ответившие. Неопрошенный сервер в план не попадает — иначе агент
    получил бы адрес, про который никто не знает, работает ли он."""

    fit: Verdict
    """Сверка с паспортом. Подсказка: развёртка получается и при вердикте «слабовато»."""

    refusals: list[Refusal] = Field(default_factory=list)
    """Что в развёртку не вошло и по какой причине. Видно рядом с тем, что вошло."""


def _instructions(seeds: list[KnowledgeSeed]) -> str:
    """Склеить знания, назвав каждое.

    Заголовок с именем семени нужен не для красоты: без него две инструкции сливаются в один
    поток, и ни человек, ни модель не могут сказать, откуда взялось конкретное правило.
    """
    return "\n\n".join(f"## {seed.name}\n\n{seed.text}" for seed in seeds)


def unfold(
    catalog: Catalog, recipe: Recipe, passport: Passport, probes: dict[str, Probe]
) -> Unfolded:
    """Развернуть рецепт под паспорт по текущему состоянию реестра."""
    knowledge: list[KnowledgeSeed] = []
    servers: list[ServerPlan] = []
    refusals: list[Refusal] = []

    for name in recipe.seeds:
        seed = catalog.seeds.get(name)
        if seed is None:
            # Причину уже назвал каталог при склейке — здесь незачем повторять её вторым голосом.
            continue

        if isinstance(seed, KnowledgeSeed):
            knowledge.append(seed)
            continue

        if isinstance(seed, ServerSeed):
            probe = probes.get(name)
            if probe is None:
                refusals.append(
                    Refusal(
                        name=RefusalName.NOT_PROBED,
                        means=(
                            f"сервер {name!r} ещё не опрашивался — неизвестно, отвечает ли он "
                            f"и что даёт"
                        ),
                        where=name,
                    )
                )
                continue
            if not probe.ok:
                refusals.extend(probe.refusals)
                continue

            servers.append(ServerPlan(seed=name, server=seed.server, tools=probe.tools))

    weights = {name: p.weight_tokens for name, p in probes.items() if p.ok}
    verdict = check(catalog.seeds_of(recipe), passport, weights)

    return Unfolded(
        recipe=recipe.name,
        passport=passport.name,
        instructions=_instructions(knowledge),
        servers=servers,
        fit=verdict,
        refusals=refusals,
    )
