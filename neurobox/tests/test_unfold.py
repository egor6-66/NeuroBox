"""Развёртка рецепта: что доезжает до агента, а что нет и почему."""

from datetime import UTC, datetime

from neurobox.mcp.probe import Probe, ToolBrief
from neurobox.model.catalog import merge
from neurobox.model.entities import KnowledgeSeed, Layer, Passport, Recipe, ServerSeed
from neurobox.model.files import LayerContents
from neurobox.model.refusal import Refusal, RefusalName
from neurobox.model.unfold import unfold


def catalog_of(*seeds: KnowledgeSeed | ServerSeed, recipe: Recipe) -> object:
    contents = LayerContents(Layer.FILE)
    for seed in seeds:
        contents.seeds[seed.name] = seed
    contents.recipes[recipe.name] = recipe
    return merge([contents])


def knowledge(name: str, text: str) -> KnowledgeSeed:
    return KnowledgeSeed(name=name, layer=Layer.FILE, text=text)


def server(name: str) -> ServerSeed:
    return ServerSeed(name=name, layer=Layer.FILE, server={"url": f"http://{name}"})


def passport() -> Passport:
    return Passport(name="п", layer=Layer.FILE, provider="openai", model="m", context=100000)


def answered(name: str, tools: list[str]) -> Probe:
    return Probe(
        seed=name,
        at=datetime.now(UTC),
        ok=True,
        tools=[ToolBrief(name=t) for t in tools],
        weight_chars=40,
    )


def test_knowledge_joined_in_recipe_order_each_named() -> None:
    recipe = Recipe(name="р", layer=Layer.FILE, seeds=["второе", "первое"])
    cat = catalog_of(knowledge("первое", "A"), knowledge("второе", "B"), recipe=recipe)

    result = unfold(cat, recipe, passport(), {})  # type: ignore[arg-type]

    # Порядок рецепта, а не алфавита: человек распоряжается им осознанно.
    assert result.instructions == "## второе\n\nB\n\n## первое\n\nA"


def test_probed_server_enters_the_plan_with_its_tools() -> None:
    recipe = Recipe(name="р", layer=Layer.FILE, seeds=["с"])
    cat = catalog_of(server("с"), recipe=recipe)

    result = unfold(cat, recipe, passport(), {"с": answered("с", ["a", "b"])})  # type: ignore[arg-type]

    assert [p.seed for p in result.servers] == ["с"]
    assert [t.name for t in result.servers[0].tools] == ["a", "b"]


def test_unprobed_server_refused_not_silently_included() -> None:
    """Адрес без опроса — это адрес, про который неизвестно, работает ли он."""
    recipe = Recipe(name="р", layer=Layer.FILE, seeds=["с"])
    cat = catalog_of(server("с"), recipe=recipe)

    result = unfold(cat, recipe, passport(), {})  # type: ignore[arg-type]

    assert result.servers == []
    assert [r.name for r in result.refusals] == [RefusalName.NOT_PROBED]


def test_failed_probe_carries_its_own_reason_forward() -> None:
    recipe = Recipe(name="р", layer=Layer.FILE, seeds=["с"])
    cat = catalog_of(server("с"), recipe=recipe)
    failed = Probe(
        seed="с",
        at=datetime.now(UTC),
        ok=False,
        refusals=[Refusal(name=RefusalName.SERVER_SILENT, means="сервер не ответил: отказ связи")],
    )

    result = unfold(cat, recipe, passport(), {"с": failed})  # type: ignore[arg-type]

    assert result.servers == []
    assert [r.name for r in result.refusals] == [RefusalName.SERVER_SILENT]
    # Причина едет ровно та, что назвал опрос — второго голоса нет.
    assert "отказ связи" in result.refusals[0].means


def test_unfolds_even_when_fit_is_weak() -> None:
    """Сверка предупреждает, а не запрещает — развёртка получается и при «слабовато»."""
    recipe = Recipe(name="р", layer=Layer.FILE, seeds=["з"])
    seed = knowledge("з", "текст")
    seed.needs.minimum.context = 1_000_000
    cat = catalog_of(seed, recipe=recipe)

    result = unfold(cat, recipe, passport(), {})  # type: ignore[arg-type]

    assert result.fit.fit.value == "weak"
    assert result.instructions.endswith("текст")


def test_missing_seed_not_reported_twice() -> None:
    """Каталог уже назвал причину при склейке — развёртка не повторяет её вторым голосом."""
    recipe = Recipe(name="р", layer=Layer.FILE, seeds=["нет-такого"])
    cat = catalog_of(recipe=recipe)

    result = unfold(cat, recipe, passport(), {})  # type: ignore[arg-type]

    assert result.refusals == []
    assert result.instructions == ""
