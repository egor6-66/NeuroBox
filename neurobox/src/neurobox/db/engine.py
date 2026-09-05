"""Подключение к базе.

Движок один на процесс и создаётся лениво — при импорте модуля соединения ещё не нужны, а
падать на старте из-за недоступной базы сервис не должен: он обязан подняться и честно сказать,
что не готов, а не умереть без объяснений.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from neurobox.core.config import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def sessions() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(engine(), expire_on_commit=False)
    return _sessionmaker


async def session() -> AsyncIterator[AsyncSession]:
    """Сессия базы на запрос. Фиксация явная: молчаливая на выходе прятала бы, что именно
    записалось, и половина ошибок всплывала бы не там, где случилась."""
    async with sessions()() as db:
        yield db


async def dispose() -> None:
    """Закрыть соединения при остановке сервиса."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def use(url: str) -> None:
    """Переключить базу — для тестов, где каждая работает на своём файле."""
    global _engine, _sessionmaker
    _engine = create_async_engine(url)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
