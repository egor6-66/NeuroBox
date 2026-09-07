"""Кто пришёл.

Один шов на все ручки. Сегодня он проверяет общий токен из окружения и отдаёт настроенного
владельца — этого хватает, пока точка входа одна. Завтра то же место спросит внешний модуль
авторизации, и поменяется только эта функция.

Своей таблицы пользователей и паролей у нас нет и не будет: их всё равно придётся выкинуть,
когда придёт общий модуль, а до тех пор они создавали бы иллюзию настоящего входа.

Что общий токен НЕ решает, и делать вид не надо: он один на всех, отозвать его у одного нельзя,
и кто именно пришёл — неизвестно. Для одной точки это честная цена; для команды нужен модуль.
"""

import logging
import secrets
from typing import Annotated

from fastapi import Cookie, Depends, Header, HTTPException, status

from neurobox.core.config import settings

log = logging.getLogger("neurobox.identity")

OPEN_PATHS = ("/health", "/ready")
"""Ручки состояния спрашивают «жив ли ты», а не «дай данные». Закрывать их значило бы, что
оркестратор снаружи не может узнать о сервисе даже того, что он поднялся."""


class Who:
    """Кто выполняет запрос."""

    def __init__(self, owner_id: str) -> None:
        self.owner_id = owner_id


def check() -> None:
    """Проверить настройки при старте.

    Отсутствие токена вне разработки — остановка, а не предупреждение: иначе сервис однажды
    поднимется открытым, и никто этого не заметит, пока не станет поздно.
    """
    if settings.environment == "local":
        return

    if not settings.access_token:
        raise RuntimeError(
            "ACCESS_TOKEN не задан. Вне разработки сервис не поднимается без него: "
            "иначе он окажется открыт всем, кто узнает адрес."
        )


COOKIE = "neurobox_token"


def who(
    authorization: Annotated[str | None, Header()] = None,
    neurobox_token: Annotated[str | None, Cookie()] = None,
) -> Who:
    """Опознать пришедшего.

    Два места намеренно. Заголовок — обычный путь. Кука — единственный возможный для потока
    событий: браузерный источник событий заголовков не задаёт, а токен в адресе осел бы в логах
    посредника и в истории браузера.
    """
    if settings.environment == "local" and not settings.access_token:
        # В разработке без токена вход открыт намеренно: поднять сервис у себя должно быть
        # можно одной командой. Вне разработки этот путь недостижим — `check()` не пустит.
        return Who(settings.owner_id)

    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif neurobox_token:
        token = neurobox_token.strip()

    # Сравнение постоянного времени: обычное «==» на строках сравнивает посимвольно и
    # выдаёт длину общего начала задержкой ответа.
    if not token or not secrets.compare_digest(token, settings.access_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="нужен токен доступа",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Who(settings.owner_id)


Caller = Annotated[Who, Depends(who)]
