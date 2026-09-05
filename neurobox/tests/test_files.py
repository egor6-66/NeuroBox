"""Чтение слоя: что прочиталось и — не менее важно — что назвало себя отказом."""

import json
from pathlib import Path

import pytest

from neurobox.model.entities import KnowledgeSeed, Layer, ServerSeed
from neurobox.model.files import read_layer
from neurobox.model.refusal import RefusalName


def write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_missing_directory_is_empty_layer_not_error(tmp_path: Path) -> None:
    contents = read_layer(tmp_path / "нет-такой", Layer.IMAGE)

    assert contents.seeds == {}
    assert contents.refusals == []


def test_server_seed_reads_mcp_json(tmp_path: Path) -> None:
    write(
        tmp_path,
        "mcp.json",
        json.dumps({"mcpServers": {"ark": {"command": "npx", "args": ["-y", "@ark-ui/mcp"]}}}),
    )

    seed = read_layer(tmp_path, Layer.FILE).seeds["ark"]

    assert isinstance(seed, ServerSeed)
    assert seed.layer is Layer.FILE
    assert seed.server["command"] == "npx"


def test_env_reference_substituted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_TOKEN", "секрет")
    write(
        tmp_path,
        "mcp.json",
        json.dumps({"mcpServers": {"s": {"headers": {"Authorization": "Bearer ${SOME_TOKEN}"}}}}),
    )

    seed = read_layer(tmp_path, Layer.FILE).seeds["s"]

    assert isinstance(seed, ServerSeed)
    assert seed.server["headers"]["Authorization"] == "Bearer секрет"
    assert seed.refusals == []


def test_missing_env_refuses_by_name_and_keeps_seed_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ABSENT_TOKEN", raising=False)
    write(
        tmp_path,
        "mcp.json",
        json.dumps({"mcpServers": {"s": {"headers": {"A": "Bearer ${ABSENT_TOKEN}"}}}}),
    )

    seed = read_layer(tmp_path, Layer.FILE).seeds["s"]

    assert isinstance(seed, ServerSeed)
    # Семя осталось на месте: пропасть молча оно не имеет права.
    assert [refusal.name for refusal in seed.refusals] == [RefusalName.ENV_MISSING]
    # Ссылка не подменена пустой строкой — иначе был бы 401 вместо названной причины.
    assert seed.server["headers"]["A"] == "Bearer ${ABSENT_TOKEN}"


def test_knowledge_seed_reads_front_matter(tmp_path: Path) -> None:
    write(
        tmp_path,
        "seeds/anything.md",
        "---\nname: дока\ndescription: как ведём\nneeds:\n  minimum:\n    context: 8000\n---\n\nтекст правил\n",
    )

    seed = read_layer(tmp_path, Layer.FILE).seeds["дока"]

    assert isinstance(seed, KnowledgeSeed)
    assert seed.text == "текст правил"
    assert seed.needs.minimum.context == 8000


def test_broken_yaml_refuses_without_killing_the_rest(tmp_path: Path) -> None:
    write(tmp_path, "passports/good.yaml", "name: хороший\nprovider: openai\nmodel: gpt-4o-mini\n")
    write(tmp_path, "passports/broken.yaml", "name: [не закрытая скобка\n")

    contents = read_layer(tmp_path, Layer.FILE)

    assert "хороший" in contents.passports
    assert [refusal.name for refusal in contents.refusals] == [RefusalName.UNREADABLE]


def test_duplicate_name_in_one_layer_refuses(tmp_path: Path) -> None:
    write(tmp_path, "passports/a.yaml", "name: один\nprovider: openai\nmodel: m\n")
    write(tmp_path, "passports/b.yaml", "name: один\nprovider: openai\nmodel: другая\n")

    contents = read_layer(tmp_path, Layer.FILE)

    assert contents.passports["один"].model == "m"
    assert [refusal.name for refusal in contents.refusals] == [RefusalName.NAME_TAKEN]
