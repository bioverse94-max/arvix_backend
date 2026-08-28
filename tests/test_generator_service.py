import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.database import SessionLocal
from api.generator_service import run_synthetic_generator

client = TestClient(app)


def test_generator_service_direct():
    db = SessionLocal()
    try:
        res = run_synthetic_generator(
            db=db,
            num_accounts=20,
            num_normal_transactions=30,
            scenarios=["mule_network"],
            seed=123,
        )
        assert res["status"] == "success"
        assert res["generated_transactions"] >= 30
        assert res["inserted_transactions"] >= 0
    finally:
        db.close()


def test_generator_api_endpoint():
    response = client.post(
        "/generator/run",
        json={
            "num_accounts": 15,
            "num_transactions": 20,
            "scenarios": ["account_takeover"],
            "seed": 99,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["generated_transactions"] >= 20
