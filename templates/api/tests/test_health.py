"""The first test, and the shape every other one should take.

It asserts the response the contract promises, through the app rather than around it.
"""

from fastapi.testclient import TestClient

from api.main import app


def test_healthz_returns_the_shape_the_contract_promises() -> None:
    response = TestClient(app).get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
