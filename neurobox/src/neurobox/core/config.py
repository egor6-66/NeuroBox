"""Настройки сервиса — только то, что кто-то действительно читает.

Поле, которое никто не читает, хуже отсутствующего: снаружи оно выглядит рабочей ручкой,
а на деле ни на что не влияет. Настройка заводится вместе с кодом, который её использует.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_name: str = "NeuroBox"
    environment: Literal["local", "staging", "production"] = "local"


settings = Settings()
