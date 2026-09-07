"""Вход: один шов на все ручки, и он не пускает без токена вне разработки."""

import pytest
from fastapi.testclient import TestClient

from neurobox.api import identity
from neurobox.core.config import settings
from neurobox.main import app


# Токен ЛАТИНИЦЕЙ: он ездит в заголовке HTTP, а туда кириллица не проходит вовсе.
@pytest.fixture()
def guarded(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "access_token", "s3cret-token")
    return TestClient(app)


def test_state_is_open_without_a_token(guarded: TestClient) -> None:
    """Снаружи спрашивают «жив ли ты», не заходя внутрь. Закрыть это значило бы, что о сервисе
    нельзя узнать даже того, что он поднялся."""
    assert guarded.get("/health").status_code == 200


def test_data_is_closed_without_a_token(guarded: TestClient) -> None:
    assert guarded.get("/catalog/recipes").status_code == 401


def test_wrong_token_is_refused(guarded: TestClient) -> None:
    response = guarded.get("/catalog/recipes", headers={"Authorization": "Bearer chuzhoy"})

    assert response.status_code == 401


def test_right_token_lets_through(guarded: TestClient) -> None:
    response = guarded.get("/catalog/recipes", headers={"Authorization": "Bearer s3cret-token"})

    assert response.status_code == 200


def test_cookie_is_not_accepted(guarded: TestClient) -> None:
    """Куку сервис не принимает намеренно: браузер не делит куки по портам, а рядом на машине
    живёт другой продукт — кука утекала бы ему на каждом запросе."""
    # Кука ставится на клиента, а не на запрос: у второго способа поведение объявлено
    # неоднозначным и он выводится из обихода.
    guarded.cookies.set("neurobox_token", "s3cret-token")

    response = guarded.get("/catalog/recipes")

    assert response.status_code == 401


def test_every_data_handle_is_closed(guarded: TestClient) -> None:
    """Проверка висит на роутере, а не на каждой ручке: забытая при втором способе оказалась бы
    открытой, и заметили бы это не мы."""
    for path in (
        "/catalog/passports",
        "/catalog/seeds",
        "/catalog/refusals",
        "/mcp/servers",
        "/agents",
        "/sessions",
    ):
        assert guarded.get(path).status_code == 401, path


def test_service_refuses_to_start_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Иначе он однажды поднимется открытым, и никто не заметит, пока не станет поздно."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "access_token", "")

    with pytest.raises(RuntimeError, match="ACCESS_TOKEN"):
        identity.check()


def test_development_stays_one_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """Поднять сервис у себя должно быть можно без настройки токена."""
    monkeypatch.setattr(settings, "environment", "local")
    monkeypatch.setattr(settings, "access_token", "")

    identity.check()
    with TestClient(app) as client:
        assert client.get("/catalog/recipes").status_code == 200
