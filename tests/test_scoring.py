"""Tests for the ML scoring integration (Parts 3-5).

Covers:
- FraudResult model creation
- Scoring interface functions (classify_risk_level, fraud reasons)
- Batch scoring API endpoint
- Fraud results API endpoints (list, get)
- FraudResult storage and deduplication
"""
import json
import pytest
from fastapi.testclient import TestClient
from api.main import app, store
from api.database import SessionLocal
from api.models import Transaction, Account, Alert, FraudResult, FraudCase, CaseEvent
from api import scoring_interface

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


def _ingest_transaction(
    txn_id="TXN_SCORE_001",
    sender="ACC_SS1",
    receiver="ACC_SR1",
    amount=5000.00,
    is_fraud=False,
):
    """Ingest a transaction via the API."""
    payload = {
        "transaction_id": txn_id,
        "utr": f"UTR{txn_id}",
        "timestamp": "2026-08-28T12:00:00Z",
        "sender_vpa": f"{sender}@upi",
        "sender_account_id": sender,
        "receiver_vpa": f"{receiver}@upi",
        "receiver_account_id": receiver,
        "amount": amount,
        "currency": "INR",
        "transaction_type": "P2P",
        "channel": "UPI",
        "status": "SUCCESS",
        "is_fraud": is_fraud,
        "fraud_scenario": None,
        "session_id": None,
    }
    resp = client.post("/transactions", json=payload)
    assert resp.json()["accepted"] == 1
    return txn_id


# ── Risk level classification ──────────────────────────────────────────

class TestRiskClassification:

    def test_critical_risk(self):
        assert scoring_interface.classify_risk_level(0.95) == "CRITICAL"
        assert scoring_interface.classify_risk_level(0.80) == "CRITICAL"

    def test_high_risk(self):
        assert scoring_interface.classify_risk_level(0.79) == "HIGH"
        assert scoring_interface.classify_risk_level(0.50) == "HIGH"

    def test_medium_risk(self):
        assert scoring_interface.classify_risk_level(0.49) == "MEDIUM"
        assert scoring_interface.classify_risk_level(0.30) == "MEDIUM"

    def test_low_risk(self):
        assert scoring_interface.classify_risk_level(0.29) == "LOW"
        assert scoring_interface.classify_risk_level(0.0) == "LOW"


# ── FraudResult model ─────────────────────────────────────────────────

class TestFraudResultModel:

    def test_create_fraud_result(self):
        _ingest_transaction(txn_id="TXN_FR_MODEL")
        db = SessionLocal()
        try:
            result = FraudResult(
                result_id="FR-test0001",
                transaction_id="TXN_FR_MODEL",
                pol_score=0.65,
                graph_score=0.72,
                final_risk_score=0.69,
                risk_level="HIGH",
                risk_flag=True,
                fraud_reasons=json.dumps(["High anomaly scores"]),
                model_version="test_v1",
            )
            db.add(result)
            db.commit()

            stored = db.query(FraudResult).filter(
                FraudResult.transaction_id == "TXN_FR_MODEL"
            ).first()
            assert stored is not None
            assert float(stored.pol_score) == pytest.approx(0.65, abs=0.01)
            assert stored.risk_level == "HIGH"
            assert stored.risk_flag is True
        finally:
            db.close()

    def test_fraud_result_one_to_one_with_transaction(self):
        """Each transaction can only have one FraudResult."""
        _ingest_transaction(txn_id="TXN_FR_UNIQUE")
        db = SessionLocal()
        try:
            result1 = FraudResult(
                result_id="FR-uniq0001",
                transaction_id="TXN_FR_UNIQUE",
                pol_score=0.5,
                risk_flag=False,
            )
            db.add(result1)
            db.commit()

            # Trying to add a second should fail
            result2 = FraudResult(
                result_id="FR-uniq0002",
                transaction_id="TXN_FR_UNIQUE",
                pol_score=0.6,
                risk_flag=False,
            )
            db.add(result2)
            with pytest.raises(Exception):
                db.commit()
            db.rollback()
        finally:
            db.close()


# ── Scoring result storage ─────────────────────────────────────────────

class TestScoringResultStorage:

    def test_store_scoring_results(self):
        _ingest_transaction(txn_id="TXN_STORE_SR")
        results = [
            scoring_interface.ScoringResult(
                transaction_id="TXN_STORE_SR",
                pol_score=0.45,
                graph_score=0.60,
                final_risk_score=0.54,
                risk_level="HIGH",
                risk_flag=True,
                fraud_reasons=["High graph score"],
            ),
        ]
        db = SessionLocal()
        try:
            stored_count = scoring_interface.store_scoring_results(results, db)
            db.commit()
            assert stored_count == 1

            fr = db.query(FraudResult).filter(
                FraudResult.transaction_id == "TXN_STORE_SR"
            ).first()
            assert fr is not None
            assert fr.risk_level == "HIGH"
            assert fr.risk_flag is True
        finally:
            db.close()

    def test_store_skips_duplicates(self):
        _ingest_transaction(txn_id="TXN_STORE_DUP")
        results = [
            scoring_interface.ScoringResult(
                transaction_id="TXN_STORE_DUP",
                pol_score=0.5,
                risk_flag=False,
            ),
        ]
        db = SessionLocal()
        try:
            count1 = scoring_interface.store_scoring_results(results, db)
            db.commit()
            assert count1 == 1

            count2 = scoring_interface.store_scoring_results(results, db)
            db.commit()
            assert count2 == 0  # skipped because already exists
        finally:
            db.close()


# ── Fraud Results API ──────────────────────────────────────────────────

class TestFraudResultsAPI:

    def _seed_result(self, txn_id="TXN_API_FR", risk_level="HIGH", risk_flag=True, score=0.65):
        _ingest_transaction(txn_id=txn_id)
        db = SessionLocal()
        result = FraudResult(
            result_id=f"FR-{txn_id[-8:]}",
            transaction_id=txn_id,
            pol_score=score * 0.8,
            graph_score=score,
            final_risk_score=score,
            risk_level=risk_level,
            risk_flag=risk_flag,
            fraud_reasons=json.dumps(["Test reason"]),
            model_version="test_v1",
        )
        db.add(result)
        db.commit()
        db.close()
        return txn_id

    def test_get_fraud_result(self):
        txn_id = self._seed_result(txn_id="TXN_GET_FR")
        resp = client.get(f"/fraud-results/{txn_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["transaction_id"] == txn_id
        assert data["risk_level"] == "HIGH"

    def test_get_nonexistent_returns_404(self):
        resp = client.get("/fraud-results/TXN_NONEXISTENT")
        assert resp.status_code == 404

    def test_list_fraud_results(self):
        self._seed_result(txn_id="TXN_LIST_FR1", risk_level="HIGH", score=0.7)
        self._seed_result(txn_id="TXN_LIST_FR2", risk_level="LOW", risk_flag=False, score=0.1)
        self._seed_result(txn_id="TXN_LIST_FR3", risk_level="CRITICAL", score=0.9)

        resp = client.get("/fraud-results")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_list_filter_by_risk_level(self):
        self._seed_result(txn_id="TXN_FILT_1", risk_level="HIGH", score=0.6)
        self._seed_result(txn_id="TXN_FILT_2", risk_level="LOW", risk_flag=False, score=0.1)

        resp = client.get("/fraud-results", params={"risk_level": "HIGH"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_filter_by_risk_flag(self):
        self._seed_result(txn_id="TXN_FLAG_1", risk_flag=True, score=0.7)
        self._seed_result(txn_id="TXN_FLAG_2", risk_flag=False, risk_level="LOW", score=0.1)

        resp = client.get("/fraud-results", params={"risk_flag": True})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_invalid_risk_level_rejected(self):
        resp = client.get("/fraud-results", params={"risk_level": "BOGUS"})
        assert resp.status_code == 400

    def test_list_pagination(self):
        for i in range(5):
            self._seed_result(txn_id=f"TXN_PAGE_{i}", score=0.5 + i * 0.05)

        resp = client.get("/fraud-results", params={"page": 1, "page_size": 2})
        data = resp.json()
        assert data["total"] == 5
        assert len(data["results"]) == 2


# ── Batch scoring endpoint ─────────────────────────────────────────────

class TestBatchScoringEndpoint:

    def test_no_transactions_returns_zero(self):
        resp = client.post("/scoring/batch", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["scored"] == 0
        assert "No unscored" in data["message"]
