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


settings = Settings()
