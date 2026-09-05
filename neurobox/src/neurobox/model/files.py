"""Чтение одного слоя конфигурации с диска.

Слой — это директория одной и той же формы: `mcp.json`, `seeds/`, `passports/`, `recipes/`.
Образ и файловый слой отличаются только путём, а не устройством, поэтому читаются одним кодом.

Сломанный файл НЕ роняет чтение и НЕ исчезает молча: он возвращается отказом с именем, и
пульт показывает его человеку. Тихо пропавший файл — худший из возможных исходов: человек
видит, что настройка не действует, и не видит, почему.
"""

import json
import os
import re
from pathlib import Path
from typing import Any

import frontmatter
import yaml
from pydantic import ValidationError

from neurobox.model.entities import (
    KnowledgeSeed,
    Layer,
    Passport,
    Recipe,
    Seed,
    ServerSeed,
)
from neurobox.model.refusal import Refusal, RefusalName

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class LayerContents:
    """Что прочиталось из одного слоя, вместе с тем, что не прочиталось."""

    def __init__(self, layer: Layer) -> None:
        self.layer = layer
        self.passports: dict[str, Passport] = {}
        self.seeds: dict[str, Seed] = {}
        self.recipes: dict[str, Recipe] = {}
        self.refusals: list[Refusal] = []

    def claim(self, kind: str, name: str, taken: bool, where: Path) -> bool:
        """Занять имя внутри слоя. Столкновение — отказ, а не молчаливая перезапись."""
        if taken:
            self.refusals.append(
                Refusal(
                    name=RefusalName.NAME_TAKEN,
                    means=f"{kind} с именем {name!r} в этом слое уже есть",
                    where=str(where),
                )
            )
            return False
        return True


def _substitute_env(value: Any, refusals: list[Refusal], where: Path) -> Any:
    """Подставить `${VAR}` из окружения. Нет переменной — отказ с именем, не пустая строка.

    Пустая строка вместо токена дала бы 401 от сервера и час поисков; названный отказ
    указывает на причину сразу.
    """
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            found = os.environ.get(name)
            if found is None:
                refusals.append(
                    Refusal(
                        name=RefusalName.ENV_MISSING,
                        means=f"переменная окружения {name!r} не задана",
                        where=str(where),
                    )
                )
                return match.group(0)
            return found

        return _ENV_REF.sub(replace, value)

    if isinstance(value, dict):
        return {k: _substitute_env(v, refusals, where) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_env(v, refusals, where) for v in value]
    return value


def _unreadable(contents: LayerContents, path: Path, why: str) -> None:
    contents.refusals.append(
        Refusal(name=RefusalName.UNREADABLE, means=why, where=str(path))
    )


def _read_servers(contents: LayerContents, root: Path) -> None:
    path = root / "mcp.json"
    if not path.is_file():
        return

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        _unreadable(contents, path, f"файл не разобрался: {error}")
        return

    servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers, dict):
        _unreadable(contents, path, "ожидался объект с ключом 'mcpServers'")
        return

    for name, entry in servers.items():
        if not isinstance(entry, dict):
            _unreadable(contents, path, f"запись {name!r} не объект")
            continue
        if not contents.claim("семя", name, name in contents.seeds, path):
            continue

        refusals: list[Refusal] = []
        resolved = _substitute_env(entry, refusals, path)
        contents.seeds[name] = ServerSeed(
            name=name, layer=contents.layer, server=resolved, refusals=refusals
        )


def _read_knowledge(contents: LayerContents, root: Path) -> None:
    folder = root / "seeds"
    if not folder.is_dir():
        return

    for path in sorted(folder.glob("*.md")):
        try:
            loaded = frontmatter.load(str(path))
        except (OSError, yaml.YAMLError) as error:
            _unreadable(contents, path, f"шапка не разобралась: {error}")
            continue

        header: dict[str, Any] = dict(loaded.metadata)
        name = str(header.get("name") or path.stem)
        if not contents.claim("семя", name, name in contents.seeds, path):
            continue

        # Разбор шапки отдаётся pydantic целиком: он же и назовёт, что именно не той формы.
        try:
            contents.seeds[name] = KnowledgeSeed.model_validate(
                {
                    **header,
                    "name": name,
                    "layer": contents.layer,
                    "text": loaded.content.strip(),
                }
            )
        except ValidationError as error:
            _unreadable(contents, path, f"шапка не той формы: {error}")


def _read_yaml_folder(
    contents: LayerContents, root: Path, folder_name: str
) -> list[tuple[str, dict[str, Any], Path]]:
    """Общий обход папки с YAML: одна форма чтения на паспорта и рецепты."""
    folder = root / folder_name
    found: list[tuple[str, dict[str, Any], Path]] = []
    if not folder.is_dir():
        return found

    for path in sorted(folder.glob("*.y*ml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            _unreadable(contents, path, f"файл не разобрался: {error}")
            continue

        if not isinstance(raw, dict):
            _unreadable(contents, path, f"ожидался объект, а не {type(raw).__name__}")
            continue

        name = str(raw.get("name") or path.stem)
        found.append((name, raw, path))

    return found


def _read_passports(contents: LayerContents, root: Path) -> None:
    for name, raw, path in _read_yaml_folder(contents, root, "passports"):
        if not contents.claim("паспорт", name, name in contents.passports, path):
            continue
        try:
            contents.passports[name] = Passport(**{**raw, "name": name, "layer": contents.layer})
        except ValidationError as error:
            _unreadable(contents, path, f"паспорт не той формы: {error}")


def _read_recipes(contents: LayerContents, root: Path) -> None:
    for name, raw, path in _read_yaml_folder(contents, root, "recipes"):
        if not contents.claim("рецепт", name, name in contents.recipes, path):
            continue
        try:
            contents.recipes[name] = Recipe(**{**raw, "name": name, "layer": contents.layer})
        except ValidationError as error:
            _unreadable(contents, path, f"рецепт не той формы: {error}")


def read_layer(root: Path, layer: Layer) -> LayerContents:
    """Прочитать директорию слоя. Отсутствующая директория — пустой слой, не ошибка."""
    contents = LayerContents(layer)
    if not root.is_dir():
        return contents

    _read_servers(contents, root)
    _read_knowledge(contents, root)
    _read_passports(contents, root)
    _read_recipes(contents, root)
    return contents
