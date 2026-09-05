"""Зависимости маршрутов.

Каталог читается с диска на каждый запрос намеренно: правка файла видна сразу, без рестарта.
Файловый слой человек правит постоянно, и «поменял, а не применилось» — самый дорогой из
возможных сюрпризов. Когда чтение станет заметно стоить, здесь появится кэш с явным сбросом,
а не молчаливое запоминание навсегда.

Зависимость — обычная функция, а не вызываемый объект: ключом подмены в тестах служит сама
функция, и подменить её можно, не угадывая, какой именно экземпляр попал в маршрут.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from neurobox.a2a.registry import Registry as AgentRegistry
from neurobox.a2a.registry import registry as agent_registry
from neurobox.core.config import settings
from neurobox.db.engine import session as db_session
from neurobox.mcp.registry import Registry, registry
from neurobox.model.catalog import Catalog, load


def get_catalog() -> Catalog:
    return load(image_dir=settings.image_config_dir, file_dir=settings.config_dir)


def get_registry() -> Registry:
    """Реестр опросов. В отличие от каталога, он не перечитывается: опрос — сетевой вызов."""
    return registry


def get_agents() -> AgentRegistry:
    """Реестр визиток агентов. Как и реестр серверов, живёт в памяти до появления базы под него."""
    return agent_registry


CurrentCatalog = Annotated[Catalog, Depends(get_catalog)]
CurrentRegistry = Annotated[Registry, Depends(get_registry)]
CurrentAgents = Annotated[AgentRegistry, Depends(get_agents)]
CurrentDb = Annotated[AsyncSession, Depends(db_session)]
