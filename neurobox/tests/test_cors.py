"""Чужие источники: пускаются только названные в настройке, и только они."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from neurobox.core.config import Settings


def test_origins_are_read_as_a_list_without_noise() -> None:
    parsed = Settings(cors_origins=" http://localhost:5174 , ,http://127.0.0.1:5174").cors_origin_list

    assert parsed == ["http://localhost:5174", "http://127.0.0.1:5174"]


def test_empty_setting_means_nobody() -> None:
    assert Settings(cors_origins="").cors_origin_list == []


def _guarded_by(origins: str) -> TestClient:
    """Тот же слой, что ставит `main`, на пустом приложении: приложение собирается один раз при
    импорте, и настройку после этого не подменить — проверяется сама связка настройка → слой."""
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=Settings(cors_origins=origins).cors_origin_list,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type", "X-User-Login"],
    )

    @app.get("/probe")
    def probe() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(app)


def test_named_origin_passes_preflight_with_our_headers() -> None:
    response = _guarded_by("http://localhost:5174").options(
        "/probe",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,x-user-login,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5174"


def test_unnamed_origin_is_refused() -> None:
    response = _guarded_by("http://localhost:5174").options(
        "/probe",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
