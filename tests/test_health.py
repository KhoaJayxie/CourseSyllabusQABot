from fastapi.testclient import TestClient

from syllabus_qa.main import app


def test_health_returns_ok_without_secrets() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
