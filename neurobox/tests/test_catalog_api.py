"""Каталог по HTTP. Зависимость подменяется целиком — глобального состояния нет."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from neurobox.api.deps import get_catalog
from neurobox.main import app
from neurobox.model.catalog import load
from tests.test_files import write


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    write(tmp_path, "passports/p.yaml", "name: п\nprovider: openai\nmodel: m\ncontext: 4000\n")
    write(
        tmp_path,
        "seeds/s.md",
        "---\nname: с\nneeds:\n  minimum:\n    context: 100000\n---\n\nтекст\n",
    )
    write(tmp_path, "recipes/r.yaml", "name: р\nseeds:\n  - с\n")

    app.dependency_overrides[get_catalog] = lambda: load(
        image_dir=tmp_path / "нет", file_dir=tmp_path
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_passports_carry_layer(client: TestClient) -> None:
    body = client.get("/catalog/passports").json()

    assert [item["name"] for item in body] == ["п"]
    assert body[0]["layer"] == "file"


def test_seeds_expose_kind(client: TestClient) -> None:
    body = client.get("/catalog/seeds").json()

    assert body[0]["kind"] == "knowledge"


def test_fit_warns_without_forbidding(client: TestClient) -> None:
    body = client.get("/catalog/recipes/р/fit/п").json()

    assert body["fit"] == "weak"
    assert body["notes"][0]["seed"] == "с"


def test_fit_404_on_unknown_names(client: TestClient) -> None:
    assert client.get("/catalog/recipes/нет/fit/п").status_code == 404
    assert client.get("/catalog/recipes/р/fit/нет").status_code == 404
