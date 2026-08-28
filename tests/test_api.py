"""Tests for the transaction ingestion API. Uses a temp file for the store
so test runs never touch data/received/transactions.jsonl."""
import os
import tempfile

os.environ["TRANSACTION_STORE_PATH"] = os.path.join(tempfile.mkdtemp(), "test_transactions.jsonl")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

import uuid
import pytest
from api.database import SessionLocal
from api.models import Transaction, Account, Alert, FraudResult, FraudCase, CaseEvent

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    """Wipe all rows before each test so tests are independent."""
    db = SessionLocal()
    db.query(CaseEvent).delete()
    db.query(FraudCase).delete()
    db.query(FraudResult).delete()
    db.query(Alert).delete()
    db.query(Transaction).delete()
    db.query(Account).delete()
    db.commit()
    db.close()
    yield


def _valid_transaction():
    unique_id = f"TXN_{uuid.uuid4().hex[:12]}"
    return {
        "transaction_id": unique_id,
        "utr": f"UTR_{uuid.uuid4().hex[:10]}",
        "timestamp": "2026-01-01T10:00:00",
        "sender_vpa": "alice01@okaxis",
        "sender_account_id": f"ACC_{uuid.uuid4().hex[:8]}",
        "receiver_vpa": "bob02@okhdfcbank",
        "receiver_account_id": f"ACC_{uuid.uuid4().hex[:8]}",
        "amount": 500.0,
        "currency": "INR",
        "transaction_type": "P2P",
        "channel": "UPI",
        "status": "SUCCESS",
        "device_id": "DEV000000000001",
        "ip_address": "10.0.0.1",
        "remarks": "",
        "is_fraud": False,
        "fraud_scenario": None,
        "session_id": None,
    }



def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_schema_endpoint():
    resp = client.get("/schema")
    assert resp.status_code == 200
    assert resp.json()["title"] == "UPI Transaction"


def test_single_valid_transaction_accepted():
    resp = client.post("/transactions", json=_valid_transaction())
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"received": 1, "accepted": 1, "rejected": []}


def test_invalid_transaction_rejected_missing_and_bad_enum():
    bad = _valid_transaction()
    del bad["amount"]
    bad["status"] = "NOT_A_STATUS"

    resp = client.post("/transactions", json=bad)
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] == 0
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["index"] == 0
    assert len(body["rejected"][0]["errors"]) >= 1


def test_batch_mixed_validity_does_not_block_valid_records():
    good = _valid_transaction()
    bad = _valid_transaction()
    del bad["sender_vpa"]

    resp = client.post("/transactions", json={"transactions": [good, bad]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] == 2
    assert body["accepted"] == 1
    assert len(body["rejected"]) == 1
    assert body["rejected"][0]["index"] == 1


def test_empty_batch_rejected():
    resp = client.post("/transactions", json={"transactions": []})
    assert resp.status_code == 400
