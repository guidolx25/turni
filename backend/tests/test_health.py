import pytest
from fastapi.testclient import TestClient

from app.main import app

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase0

client = TestClient(app)


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
