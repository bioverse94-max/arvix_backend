import pytest
from fastapi.testclient import TestClient
from api.main import app, store
from api.database import SessionLocal
from api.models import Transaction, Account

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_db():
    db = SessionLocal()
    db.query(Transaction).delete()
    db.query(Account).delete()
    db.commit()
    db.close()
    yield

def build_valid_transaction(txn_id="TXN123", sender="ACC1", receiver="ACC2"):
    return {
        "transaction_id": txn_id,
        "utr": f"UTR{txn_id}",
        "timestamp": "2026-08-26T12:00:00Z",
        "sender_vpa": f"{sender}@upi",
        "sender_account_id": sender,
        "receiver_vpa": f"{receiver}@upi",
        "receiver_account_id": receiver,
        "amount": 150.50,
        "currency": "INR",
        "transaction_type": "P2P",
        "channel": "UPI",
        "status": "SUCCESS",
        "is_fraud": False
    }

def test_valid_transaction_is_stored():
    payload = build_valid_transaction()
    response = client.post("/transactions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 1
    assert len(data["rejected"]) == 0

    # Verify retrieved from DB
    db = SessionLocal()
    txn = db.query(Transaction).filter_by(transaction_id="TXN123").first()
    assert txn is not None
    assert float(txn.amount) == 150.50
    db.close()

def test_sender_receiver_account_relationship_works():
    payload = build_valid_transaction()
    client.post("/transactions", json=payload)

    db = SessionLocal()
    txn = db.query(Transaction).filter_by(transaction_id="TXN123").first()
    assert txn.sender.account_id == "ACC1"
    assert txn.receiver.account_id == "ACC2"
    assert txn.sender.is_stub is True
    assert txn.receiver.is_stub is True
    db.close()

def test_duplicate_txn_id_is_rejected():
    payload = build_valid_transaction()
    # First insert
    response1 = client.post("/transactions", json=payload)
    assert response1.status_code == 200
    assert response1.json()["accepted"] == 1

    # Second insert with same txn_id
    response2 = client.post("/transactions", json=payload)
    assert response2.status_code == 200
    data = response2.json()
    assert data["accepted"] == 0
    assert len(data["rejected"]) == 1
    assert "Duplicate transaction_id" in data["rejected"][0]["errors"][0]

def test_invalid_transaction_is_not_stored():
    payload = build_valid_transaction()
    payload.pop("amount") # make it invalid
    
    response = client.post("/transactions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 0
    assert len(data["rejected"]) == 1
    
    # Ensure nothing was stored
    db = SessionLocal()
    assert db.query(Transaction).count() == 0
    db.close()

def test_self_transfer_same_sender_receiver():
    payload = build_valid_transaction(txn_id="TXN_SELF", sender="ACC_SAME", receiver="ACC_SAME")
    response = client.post("/transactions", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] == 1, data.get("rejected")

    db = SessionLocal()
    txn = db.query(Transaction).filter_by(transaction_id="TXN_SELF").first()
    assert txn.sender_account_id == "ACC_SAME"
    assert txn.receiver_account_id == "ACC_SAME"
    
    # Both references point to the same account record
    assert txn.sender.account_id == txn.receiver.account_id
    
    # There should only be one account record created
    assert db.query(Account).count() == 1
    db.close()
