import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Асинхронные тесты гоняются только на asyncio: trio в зависимостях нет и не нужен."""
    return "asyncio"
