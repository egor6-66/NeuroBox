"""Склейка слоёв и сверка требований."""

from pathlib import Path

from neurobox.model.catalog import load, merge
from neurobox.model.entities import Demands, Layer, Needs, Passport
from neurobox.model.files import LayerContents
from neurobox.model.fit import Fit, check
from neurobox.model.refusal import RefusalName
from tests.test_files import write


def passport(**overrides: object) -> Passport:
    base: dict[str, object] = {
        "name": "п",
        "layer": Layer.FILE,
        "provider": "openai",
        "model": "m",
    }
    return Passport(**{**base, **overrides})  # type: ignore[arg-type]


def knowledge(name: str, layer: Layer, minimum: Demands | None = None, hint: str | None = None):  # type: ignore[no-untyped-def]
    from neurobox.model.entities import KnowledgeSeed

    return KnowledgeSeed(
        name=name,
        layer=layer,
        text="…",
        needs=Needs(minimum=minimum or Demands(), hint=hint),
    )


# --- слои ------------------------------------------------------------------


def test_upper_layer_overrides_lower_by_name() -> None:
    image = LayerContents(Layer.IMAGE)
    image.passports["п"] = passport(layer=Layer.IMAGE, model="из-образа")
    file = LayerContents(Layer.FILE)
    file.passports["п"] = passport(layer=Layer.FILE, model="из-файла")

    catalog = merge([image, file])

    assert catalog.passports["п"].model == "из-файла"
    assert catalog.passports["п"].layer is Layer.FILE


def test_element_carries_its_layer(tmp_path: Path) -> None:
    write(tmp_path / "img", "passports/a.yaml", "name: только-в-образе\nprovider: o\nmodel: m\n")
    write(tmp_path / "usr", "passports/b.yaml", "name: только-в-файле\nprovider: o\nmodel: m\n")

    catalog = load(image_dir=tmp_path / "img", file_dir=tmp_path / "usr")

    assert catalog.passports["только-в-образе"].layer is Layer.IMAGE
    assert catalog.passports["только-в-файле"].layer is Layer.FILE


def test_recipe_pointing_at_nothing_stays_visible_with_named_refusal() -> None:
    from neurobox.model.entities import Recipe

    file = LayerContents(Layer.FILE)
    file.recipes["р"] = Recipe(name="р", layer=Layer.FILE, seeds=["нет-такого"])

    catalog = merge([file])

    assert "р" in catalog.recipes
    assert [refusal.name for refusal in catalog.refusals] == [RefusalName.SEED_UNKNOWN]


# --- сверка ----------------------------------------------------------------


def test_fits_when_minimum_met() -> None:
    seed = knowledge("с", Layer.FILE, minimum=Demands(context=1000))

    assert check([seed], passport(context=4000)).fit is Fit.FITS


def test_weak_when_below_minimum_but_never_blocks() -> None:
    seed = knowledge("с", Layer.FILE, minimum=Demands(context=100000))

    verdict = check([seed], passport(context=4000))

    assert verdict.fit is Fit.WEAK
    assert "меньше требуемых" in verdict.notes[0].means


def test_unknown_when_passport_silent() -> None:
    seed = knowledge("с", Layer.FILE, minimum=Demands(context=100000))

    # Паспорт не заявил окно — это незнание, а не несоответствие.
    assert check([seed], passport()).fit is Fit.UNKNOWN


def test_unknown_when_seed_demands_nothing() -> None:
    assert check([knowledge("с", Layer.FILE)], passport(context=4000)).fit is Fit.UNKNOWN


def test_hint_is_carried_but_does_not_affect_verdict() -> None:
    seed = knowledge("с", Layer.FILE, minimum=Demands(context=1000), hint="нужна умная модель")

    verdict = check([seed], passport(context=4000))

    assert verdict.fit is Fit.FITS
    assert verdict.hints == ["нужна умная модель"]
