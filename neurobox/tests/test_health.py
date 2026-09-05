from fastapi.testclient import TestClient

from neurobox.main import app

client = TestClient(app)


def test_health_says_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
