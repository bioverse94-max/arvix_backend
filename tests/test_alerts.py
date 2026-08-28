"""Tests for the alert system (Part 6).

Covers:
- Alert auto-creation when a fraudulent transaction is ingested
- No alert for non-fraudulent transactions
- Severity mapping per fraud scenario
- GET /alerts with filtering and pagination
- GET /alerts/{alert_id}
- PATCH /alerts/{alert_id} status transitions
- GET /alerts/statistics
- No duplicate alerts for the same transaction
"""
import pytest
from fastapi.testclient import TestClient
from api.main import app, store
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


def _build_transaction(
    txn_id="TXN_ALERT_001",
    sender="ACC_S1",
    receiver="ACC_R1",
    amount=5000.00,
    is_fraud=False,
    fraud_scenario=None,
):
    """Build a valid transaction payload for POST /transactions."""
    return {
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
        "fraud_scenario": fraud_scenario,
        "session_id": None,
    }


# ── Alert auto-creation ───────────────────────────────────────────────

class TestAlertAutoCreation:
    """Alerts should be auto-created when fraudulent transactions arrive."""

    def test_fraudulent_transaction_creates_alert(self):
        payload = _build_transaction(
            txn_id="TXN_FRAUD_1",
            is_fraud=True,
            fraud_scenario="account_takeover",
            amount=45000.00,
        )
        resp = client.post("/transactions", json=payload)
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 1

        db = SessionLocal()
        alerts = db.query(Alert).filter(Alert.transaction_id == "TXN_FRAUD_1").all()
        assert len(alerts) == 1

        alert = alerts[0]
        assert alert.alert_type == "FRAUD_DETECTED"
        assert alert.severity == "CRITICAL"  # account_takeover -> CRITICAL
        assert alert.status == "OPEN"
        assert "Account Takeover" in alert.title
        assert "45,000.00" in alert.title
        assert alert.fraud_scenario == "account_takeover"
        db.close()

    def test_non_fraudulent_transaction_creates_no_alert(self):
        payload = _build_transaction(txn_id="TXN_CLEAN_1", is_fraud=False)
        resp = client.post("/transactions", json=payload)
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 1

        db = SessionLocal()
        alerts = db.query(Alert).all()
        assert len(alerts) == 0
        db.close()

    def test_no_duplicate_alert_for_same_transaction(self):
        """Posting the same fraud transaction twice should reject the duplicate
        (duplicate transaction_id), so only one alert is created."""
        payload = _build_transaction(
            txn_id="TXN_DUP_1", is_fraud=True, fraud_scenario="fan_in"
        )
        # First POST — accepted
        resp1 = client.post("/transactions", json=payload)
        assert resp1.json()["accepted"] == 1

        # Second POST — duplicate txn_id rejected
        resp2 = client.post("/transactions", json=payload)
        assert resp2.json()["accepted"] == 0

        db = SessionLocal()
        alerts = db.query(Alert).filter(Alert.transaction_id == "TXN_DUP_1").all()
        assert len(alerts) == 1
        db.close()


# ── Severity mapping ──────────────────────────────────────────────────

class TestSeverityMapping:
    """Each fraud scenario should map to the correct severity level."""

    @pytest.mark.parametrize(
        "scenario,expected_severity",
        [
            ("account_takeover", "CRITICAL"),
            ("mule_network", "HIGH"),
            ("circular_flow", "HIGH"),
            ("fan_in", "MEDIUM"),
            ("fan_out", "MEDIUM"),
            ("rapid_pass_through", "MEDIUM"),
        ],
    )
    def test_severity_per_scenario(self, scenario, expected_severity):
        txn_id = f"TXN_SEV_{scenario}"
        payload = _build_transaction(
            txn_id=txn_id, is_fraud=True, fraud_scenario=scenario
        )
        client.post("/transactions", json=payload)

        db = SessionLocal()
        alert = db.query(Alert).filter(Alert.transaction_id == txn_id).first()
        assert alert is not None, f"No alert created for scenario '{scenario}'"
        assert alert.severity == expected_severity
        db.close()

    def test_unknown_scenario_defaults_to_medium(self):
        payload = _build_transaction(
            txn_id="TXN_UNKNOWN_SCENARIO",
            is_fraud=True,
            fraud_scenario="some_new_scenario",
        )
        client.post("/transactions", json=payload)

        db = SessionLocal()
        alert = db.query(Alert).filter(
            Alert.transaction_id == "TXN_UNKNOWN_SCENARIO"
        ).first()
        assert alert is not None
        assert alert.severity == "MEDIUM"
        db.close()


# ── GET /alerts ────────────────────────────────────────────────────────

class TestListAlerts:

    def _seed_alerts(self, count=5):
        """Insert several fraud transactions to generate alerts."""
        for i in range(count):
            scenario = ["account_takeover", "mule_network", "fan_in"][i % 3]
            payload = _build_transaction(
                txn_id=f"TXN_LIST_{i}",
                sender=f"ACC_LS_{i}",
                receiver=f"ACC_LR_{i}",
                is_fraud=True,
                fraud_scenario=scenario,
            )
            client.post("/transactions", json=payload)

    def test_list_alerts_returns_all(self):
        self._seed_alerts(3)
        resp = client.get("/alerts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["alerts"]) == 3

    def test_list_alerts_filter_by_severity(self):
        self._seed_alerts(6)
        resp = client.get("/alerts", params={"severity": "CRITICAL"})
        assert resp.status_code == 200
        data = resp.json()
        # account_takeover indices: 0, 3 → 2 CRITICAL alerts
        assert data["total"] == 2
        for alert in data["alerts"]:
            assert alert["severity"] == "CRITICAL"

    def test_list_alerts_filter_by_status(self):
        self._seed_alerts(3)
        # All alerts start as OPEN
        resp = client.get("/alerts", params={"status": "OPEN"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

        resp = client.get("/alerts", params={"status": "RESOLVED"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_list_alerts_pagination(self):
        self._seed_alerts(5)
        resp = client.get("/alerts", params={"page": 1, "page_size": 2})
        data = resp.json()
        assert data["total"] == 5
        assert len(data["alerts"]) == 2
        assert data["page"] == 1
        assert data["page_size"] == 2

        resp2 = client.get("/alerts", params={"page": 3, "page_size": 2})
        data2 = resp2.json()
        assert len(data2["alerts"]) == 1  # 5th alert on page 3

    def test_list_alerts_invalid_status_rejected(self):
        resp = client.get("/alerts", params={"status": "BOGUS"})
        assert resp.status_code == 400

    def test_list_alerts_invalid_severity_rejected(self):
        resp = client.get("/alerts", params={"severity": "LOW"})
        assert resp.status_code == 400


# ── GET /alerts/{alert_id} ─────────────────────────────────────────────

class TestGetAlert:

    def test_get_existing_alert(self):
        payload = _build_transaction(
            txn_id="TXN_GET_1", is_fraud=True, fraud_scenario="mule_network"
        )
        client.post("/transactions", json=payload)

        # Find the alert_id
        db = SessionLocal()
        alert = db.query(Alert).filter(Alert.transaction_id == "TXN_GET_1").first()
        alert_id = alert.alert_id
        db.close()

        resp = client.get(f"/alerts/{alert_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alert_id"] == alert_id
        assert data["transaction_id"] == "TXN_GET_1"
        assert data["severity"] == "HIGH"

    def test_get_nonexistent_alert_returns_404(self):
        resp = client.get("/alerts/ALT-nonexistent")
        assert resp.status_code == 404


# ── PATCH /alerts/{alert_id} ───────────────────────────────────────────

class TestUpdateAlert:

    def _create_and_get_alert_id(self, txn_id="TXN_PATCH"):
        payload = _build_transaction(
            txn_id=txn_id, is_fraud=True, fraud_scenario="fan_out"
        )
        client.post("/transactions", json=payload)
        db = SessionLocal()
        alert = db.query(Alert).filter(Alert.transaction_id == txn_id).first()
        alert_id = alert.alert_id
        db.close()
        return alert_id

    def test_update_status_to_acknowledged(self):
        alert_id = self._create_and_get_alert_id("TXN_ACK")
        resp = client.patch(f"/alerts/{alert_id}", json={"status": "ACKNOWLEDGED"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ACKNOWLEDGED"
        assert resp.json()["resolved_at"] is None  # Not a terminal status

    def test_update_status_to_resolved_sets_resolved_at(self):
        alert_id = self._create_and_get_alert_id("TXN_RESOLVE")
        resp = client.patch(
            f"/alerts/{alert_id}",
            json={"status": "RESOLVED", "resolution_notes": "Confirmed fraud, case filed."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RESOLVED"
        assert data["resolved_at"] is not None
        assert data["resolution_notes"] == "Confirmed fraud, case filed."

    def test_update_status_to_dismissed_sets_resolved_at(self):
        alert_id = self._create_and_get_alert_id("TXN_DISMISS")
        resp = client.patch(
            f"/alerts/{alert_id}",
            json={"status": "DISMISSED", "resolution_notes": "False positive."},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "DISMISSED"
        assert data["resolved_at"] is not None

    def test_reopen_clears_resolved_at(self):
        alert_id = self._create_and_get_alert_id("TXN_REOPEN")
        # Resolve it first
        client.patch(f"/alerts/{alert_id}", json={"status": "RESOLVED"})
        # Re-open it
        resp = client.patch(f"/alerts/{alert_id}", json={"status": "OPEN"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "OPEN"
        assert resp.json()["resolved_at"] is None

    def test_assign_analyst(self):
        alert_id = self._create_and_get_alert_id("TXN_ASSIGN")
        resp = client.patch(
            f"/alerts/{alert_id}", json={"assigned_to": "analyst_ravi"}
        )
        assert resp.status_code == 200
        assert resp.json()["assigned_to"] == "analyst_ravi"

    def test_update_invalid_status_rejected(self):
        alert_id = self._create_and_get_alert_id("TXN_BAD_STATUS")
        resp = client.patch(f"/alerts/{alert_id}", json={"status": "INVALID"})
        assert resp.status_code == 400

    def test_update_nonexistent_alert_returns_404(self):
        resp = client.patch("/alerts/ALT-nonexistent", json={"status": "OPEN"})
        assert resp.status_code == 404


# ── GET /alerts/statistics ─────────────────────────────────────────────

class TestAlertStatistics:

    def test_empty_statistics(self):
        resp = client.get("/alerts/statistics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_alerts"] == 0
        assert data["open_alerts"] == 0

    def test_statistics_after_ingestion(self):
        # Create 3 fraud transactions
        for i, scenario in enumerate(["account_takeover", "mule_network", "fan_in"]):
            payload = _build_transaction(
                txn_id=f"TXN_STAT_{i}",
                sender=f"ACC_ST_S{i}",
                receiver=f"ACC_ST_R{i}",
                is_fraud=True,
                fraud_scenario=scenario,
            )
            client.post("/transactions", json=payload)

        resp = client.get("/alerts/statistics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_alerts"] == 3
        assert data["open_alerts"] == 3
        assert data["resolved_alerts"] == 0

        # Check by_severity has entries
        severities = {s["severity"]: s["count"] for s in data["by_severity"]}
        assert severities.get("CRITICAL", 0) == 1  # account_takeover
        assert severities.get("HIGH", 0) == 1      # mule_network
        assert severities.get("MEDIUM", 0) == 1    # fan_in

    def test_statistics_after_status_updates(self):
        # Create 2 alerts
        for i in range(2):
            payload = _build_transaction(
                txn_id=f"TXN_STAT_UPD_{i}",
                sender=f"ACC_SU_S{i}",
                receiver=f"ACC_SU_R{i}",
                is_fraud=True,
                fraud_scenario="fan_out",
            )
            client.post("/transactions", json=payload)

        # Resolve one alert
        db = SessionLocal()
        alert = db.query(Alert).first()
        alert_id = alert.alert_id
        db.close()
        client.patch(f"/alerts/{alert_id}", json={"status": "RESOLVED"})

        resp = client.get("/alerts/statistics")
        data = resp.json()
        assert data["total_alerts"] == 2
        assert data["open_alerts"] == 1
        assert data["resolved_alerts"] == 1
