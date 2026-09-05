"""Каталог по HTTP: паспорта, семена, рецепты — и то, что с ними не так.

Отказы отдаются рядом с содержимым, а не вместо него: сломанный файл не должен прятать
остальные. Метка слоя едет с каждым элементом — это её единственный смысл.
"""

from fastapi import APIRouter, HTTPException

from neurobox.api.deps import CurrentCatalog, CurrentRegistry
from neurobox.model.entities import Passport, Recipe, Seed
from neurobox.model.fit import Verdict, check
from neurobox.model.refusal import Refusal

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/passports")
def passports(catalog: CurrentCatalog) -> list[Passport]:
    return list(catalog.passports.values())


@router.get("/seeds")
def seeds(catalog: CurrentCatalog) -> list[Seed]:
    return list(catalog.seeds.values())


@router.get("/recipes")
def recipes(catalog: CurrentCatalog) -> list[Recipe]:
    return list(catalog.recipes.values())


@router.get("/refusals")
def refusals(catalog: CurrentCatalog) -> list[Refusal]:
    """Всё, что не прочиталось или не сошлось, одним списком."""
    return catalog.refusals


@router.get("/recipes/{recipe}/fit/{passport}")
def fit(
    recipe: str, passport: str, catalog: CurrentCatalog, registry: CurrentRegistry
) -> Verdict:
    """Сверка рецепта с паспортом — подсказка перед запуском, а не разрешение на него."""
    if recipe not in catalog.recipes:
        raise HTTPException(status_code=404, detail=f"рецепта {recipe!r} нет")
    if passport not in catalog.passports:
        raise HTTPException(status_code=404, detail=f"паспорта {passport!r} нет")

    chosen = catalog.recipes[recipe]
    weights = {p.seed: p.weight_tokens for p in registry.known() if p.ok}
    return check(catalog.seeds_of(chosen), catalog.passports[passport], weights)
