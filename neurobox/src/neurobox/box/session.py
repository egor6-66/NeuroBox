"""Из какой сессии позвали наш инструмент.

Сессия приходит заголовком, который подставила развёртка: спрашивать у агента, где он
находится, значило бы доверять его догадке о собственном контексте.

Заголовок читается обёрткой вокруг приложения, а не внутри самой ручки. Так это не зависит от
того, как именно текущая версия SDK передаёт контекст в обработчик: транспорт у протокола свой и
меняется, а заголовки HTTP — нет.
"""

from collections.abc import Awaitable, Callable, MutableMapping
from contextvars import ContextVar
from typing import Any

HEADER = b"x-neurobox-session"

current: ContextVar[str | None] = ContextVar("box_session", default=None)

# Формы ASGI берутся именно такими, какие у него в договоре: словарь тут не подойдёт, потому
# что приложения объявляют изменяемое отображение, и подмена сузила бы совместимость.
Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]


class Mount:
    """Точка монтирования нашего сервера.

    Приложение подставляется при СТАРТЕ, а не при импорте: менеджер сессий протокола можно
    запустить один раз на экземпляр, и собранный заранее переживает только первый запуск —
    второй (тесты, перезагрузка, повторный вход в жизненный цикл) падает с невнятной ошибкой.

    Заодно кладёт сессию из заголовка в переменную на время запроса.
    """

    def __init__(self) -> None:
        self._app: App | None = None

    def use(self, app: App) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = self._app
        if app is None:
            # Обращение до старта — состояние, которого быть не должно. Молчать нельзя:
            # пустой ответ выглядел бы как «сервера нет», а он есть и просто не готов.
            raise RuntimeError("сервер бокса ещё не поднят")

        if scope.get("type") != "http":
            await app(scope, receive, send)
            return

        found = next(
            (value for name, value in scope.get("headers") or [] if name.lower() == HEADER),
            b"",
        )
        token = current.set(found.decode("utf-8").strip() or None)
        try:
            await app(scope, receive, send)
        finally:
            # Сброс обязателен: переменная переживает запрос, и следующий получил бы чужую
            # сессию — заметка ушла бы не в тот разговор, и никто бы не понял почему.
            current.reset(token)
