"""Каталог — то, что получилось после склейки слоёв.

Слои складываются по порядку: образ, файл, база. Одноимённый элемент верхнего слоя перекрывает
нижний целиком, а не по полям — частичное слияние двух источников дало бы элемент, которого нет
ни в одном файле, и человек не смог бы найти, откуда взялось значение.

Каждый элемент несёт метку своего слоя. Без неё три слоя превращаются в гадание.
"""

from pathlib import Path

from pydantic import BaseModel, Field

from neurobox.model.entities import Agent, Layer, Passport, Recipe, Seed, ServerSeed
from neurobox.model.files import LayerContents, read_layer
from neurobox.model.refusal import Refusal, RefusalName


class Catalog(BaseModel):
    passports: dict[str, Passport] = Field(default_factory=dict)
    seeds: dict[str, Seed] = Field(default_factory=dict)
    recipes: dict[str, Recipe] = Field(default_factory=dict)
    agents: dict[str, Agent] = Field(default_factory=dict)

    refusals: list[Refusal] = Field(default_factory=list)
    """Всё, что не прочиталось или не сошлось. Видно целиком, а не по одному за прогон."""

    def seeds_of(self, recipe: Recipe) -> list[Seed]:
        """Семена рецепта в порядке объявления. Незнакомые пропускаются — их назвал отказ."""
        return [self.seeds[name] for name in recipe.seeds if name in self.seeds]


def _check_recipe_seeds(catalog: Catalog) -> None:
    """Рецепт, ссылающийся в пустоту, остаётся видимым — но с названной причиной.

    Убрать его из списка значило бы, что человек ищет пропавший рецепт вместо того, чтобы
    читать, какого семени не хватает.
    """
    for recipe in catalog.recipes.values():
        for name in recipe.seeds:
            if name not in catalog.seeds:
                catalog.refusals.append(
                    Refusal(
                        name=RefusalName.SEED_UNKNOWN,
                        means=f"рецепт {recipe.name!r} ссылается на семя {name!r}, которого нет",
                        where=recipe.name,
                    )
                )


def merge(layers: list[LayerContents]) -> Catalog:
    """Сложить слои в порядке от нижнего к верхнему."""
    catalog = Catalog()

    for contents in layers:
        catalog.passports.update(contents.passports)
        catalog.seeds.update(contents.seeds)
        catalog.recipes.update(contents.recipes)
        catalog.agents.update(contents.agents)
        catalog.refusals.extend(contents.refusals)

    _check_recipe_seeds(catalog)
    return catalog


def _builtin() -> LayerContents:
    """Наши собственные серверы — нижний слой каталога.

    Они видны наравне со всеми, и рецепт решает, давать ли их агенту. Адрес подставляется на
    развёртке: он зависит от того, откуда агент до нас достучится, и в файле его записать
    нельзя.
    """
    from neurobox.box.registry import OWN

    contents = LayerContents(Layer.BUILTIN)
    for own in OWN:
        contents.seeds[own.name] = ServerSeed(
            name=own.name,
            layer=Layer.BUILTIN,
            description=own.description,
            server={"type": "http", "own": own.name},
        )
    return contents


def load(image_dir: Path, file_dir: Path) -> Catalog:
    """Собрать каталог из существующих сегодня слоёв.

    Слой базы появится вместе с базой и встанет последним — порядок склейки уже её ждёт.
    """
    return merge(
        [
            _builtin(),
            read_layer(image_dir, Layer.IMAGE),
            read_layer(file_dir, Layer.FILE),
        ]
    )
