"""Настройки сервиса — только то, что кто-то действительно читает.

Поле, которое никто не читает, хуже отсутствующего: снаружи оно выглядит рабочей ручкой,
а на деле ни на что не влияет. Настройка заводится вместе с кодом, который её использует.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_name: str = "NeuroBox"
    environment: Literal["local", "staging", "production"] = "local"

    config_dir: Path = Path("/config")
    """Файловый слой — то, что человек правит и коммитит. В образ монтируется снаружи."""

    image_config_dir: Path = Path("/opt/neurobox/defaults")
    """Слой образа — запечённые эталоны. Директории может не быть: это пустой слой, не ошибка."""

    database_url: str = "postgresql+asyncpg://neurobox:neurobox@db:5432/neurobox"
    """Адрес базы. Значение по умолчанию — имена из compose: на чистом клоне работает без правки."""

    owner_id: str = "local"
    """Владелец сессий, пока входа нет. Поле существует с первого дня намеренно: приписать
    владельца живым сессиям потом значило бы выбирать, кому они принадлежат."""


settings = Settings()
