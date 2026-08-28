"""Tests for the fraud case system (Part 7).

Covers:
- Create case from alert
- Cannot create duplicate case for same alert
- Alert status updated to INVESTIGATING on case creation
- List cases with filtering (status, priority, assigned_to)
- Get case with full details and timeline
- Update case status/priority/assignment/findings
- Add investigation notes
- Close case as confirmed fraud → alert RESOLVED
- Close case as false positive → alert DISMISSED
- Case timeline records all events
- Case statistics
- 404 for nonexistent case
"""
import pytest
from fastapi.testclient import TestClient
from api.main import app, store
from api.database import SessionLocal
from api.models import Transaction, Account, Alert, FraudCase, CaseEvent, FraudResult

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


def _ingest_fraud_transaction(
    txn_id="TXN_CASE_001",
    sender="ACC_CS1",
    receiver="ACC_CR1",
    amount=25000.00,
    fraud_scenario="account_takeover",
):
    """Ingest a fraud transaction and return its alert_id."""
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
        "is_fraud": True,
        "fraud_scenario": fraud_scenario,
        "session_id": None,
    }
    resp = client.post("/transactions", json=payload)
    assert resp.json()["accepted"] == 1

    db = SessionLocal()
    alert = db.query(Alert).filter(Alert.transaction_id == txn_id).first()
    alert_id = alert.alert_id
    db.close()
    return alert_id


# ── Case creation ──────────────────────────────────────────────────────

class TestCaseCreation:

    def test_create_case_from_alert(self):
        alert_id = _ingest_fraud_transaction()
        resp = client.post("/cases", json={
            "alert_id": alert_id,
            "assigned_to": "analyst_priya",
            "priority": "HIGH",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["alert_id"] == alert_id
        assert data["status"] == "OPEN"
        assert data["priority"] == "HIGH"
        assert data["assigned_to"] == "analyst_priya"
        assert "Investigation:" in data["title"]
        assert data["case_id"].startswith("CASE-")

    def test_create_case_sets_alert_to_investigating(self):
        alert_id = _ingest_fraud_transaction(txn_id="TXN_ALERT_STATUS")
        client.post("/cases", json={"alert_id": alert_id})

        db = SessionLocal()
        alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
        assert alert.status == "INVESTIGATING"
        db.close()

    def test_create_case_default_priority_is_medium(self):
        alert_id = _ingest_fraud_transaction(txn_id="TXN_DEFAULT_PRI")
        resp = client.post("/cases", json={"alert_id": alert_id})
        assert resp.status_code == 201
        assert resp.json()["priority"] == "MEDIUM"

    def test_duplicate_case_for_same_alert_rejected(self):
        alert_id = _ingest_fraud_transaction(txn_id="TXN_DUP_CASE")
        resp1 = client.post("/cases", json={"alert_id": alert_id})
        assert resp1.status_code == 201

        resp2 = client.post("/cases", json={"alert_id": alert_id})
        assert resp2.status_code == 400
        assert "already has case" in resp2.json()["detail"]

    def test_create_case_nonexistent_alert_rejected(self):
        resp = client.post("/cases", json={"alert_id": "ALT-nonexistent"})
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]

    def test_create_case_invalid_priority_rejected(self):
        alert_id = _ingest_fraud_transaction(txn_id="TXN_BAD_PRI")
        resp = client.post("/cases", json={
            "alert_id": alert_id,
            "priority": "SUPER_URGENT",
        })
        assert resp.status_code == 400
        assert "Invalid priority" in resp.json()["detail"]

    def test_create_case_records_created_event(self):
        alert_id = _ingest_fraud_transaction(txn_id="TXN_CREATED_EVT")
        resp = client.post("/cases", json={
            "alert_id": alert_id,
            "assigned_to": "analyst_ravi",
        })
        case_id = resp.json()["case_id"]

        # Check timeline
        timeline_resp = client.get(f"/cases/{case_id}/timeline")
        assert timeline_resp.status_code == 200
        events = timeline_resp.json()
        assert len(events) == 1
        assert events[0]["event_type"] == "CREATED"
        assert alert_id in events[0]["description"]


# ── List cases ─────────────────────────────────────────────────────────

class TestListCases:

    def _seed_cases(self, count=3):
        """Create multiple fraud cases."""
        case_ids = []
        for i in range(count):
            scenario = ["account_takeover", "mule_network", "fan_in"][i % 3]
            priority = ["CRITICAL", "HIGH", "MEDIUM"][i % 3]
            alert_id = _ingest_fraud_transaction(
                txn_id=f"TXN_LIST_C_{i}",
                sender=f"ACC_LC_S{i}",
                receiver=f"ACC_LC_R{i}",
                fraud_scenario=scenario,
            )
            resp = client.post("/cases", json={
                "alert_id": alert_id,
                "priority": priority,
                "assigned_to": f"analyst_{i}",
            })
            case_ids.append(resp.json()["case_id"])
        return case_ids

    def test_list_all_cases(self):
        self._seed_cases(3)
        resp = client.get("/cases")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert len(data["cases"]) == 3

    def test_list_cases_filter_by_status(self):
        self._seed_cases(3)
        resp = client.get("/cases", params={"status": "OPEN"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

    def test_list_cases_filter_by_priority(self):
        self._seed_cases(3)
        resp = client.get("/cases", params={"priority": "CRITICAL"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_cases_filter_by_assigned_to(self):
        self._seed_cases(3)
        resp = client.get("/cases", params={"assigned_to": "analyst_0"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_list_cases_pagination(self):
        self._seed_cases(3)
        resp = client.get("/cases", params={"page": 1, "page_size": 2})
        data = resp.json()
        assert data["total"] == 3
        assert len(data["cases"]) == 2

    def test_list_cases_invalid_status_rejected(self):
        resp = client.get("/cases", params={"status": "BOGUS"})
        assert resp.status_code == 400


# ── Get case ───────────────────────────────────────────────────────────

class TestGetCase:

    def test_get_existing_case(self):
        alert_id = _ingest_fraud_transaction(txn_id="TXN_GET_CASE")
        create_resp = client.post("/cases", json={"alert_id": alert_id})
        case_id = create_resp.json()["case_id"]

        resp = client.get(f"/cases/{case_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == case_id
        assert data["alert"] is not None
        assert data["alert"]["alert_id"] == alert_id
        assert len(data["events"]) >= 1  # At least the CREATED event

    def test_get_nonexistent_case_returns_404(self):
        resp = client.get("/cases/CASE-nonexistent")
        assert resp.status_code == 404


# ── Update case ────────────────────────────────────────────────────────

class TestUpdateCase:

    def _create_case(self, txn_id="TXN_UPD"):
        alert_id = _ingest_fraud_transaction(txn_id=txn_id)
        resp = client.post("/cases", json={"alert_id": alert_id})
        return resp.json()["case_id"]

    def test_update_status(self):
        case_id = self._create_case("TXN_UPD_STATUS")
        resp = client.patch(f"/cases/{case_id}", json={"status": "INVESTIGATING"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "INVESTIGATING"

    def test_update_priority(self):
        case_id = self._create_case("TXN_UPD_PRI")
        resp = client.patch(f"/cases/{case_id}", json={"priority": "CRITICAL"})
        assert resp.status_code == 200
        assert resp.json()["priority"] == "CRITICAL"

    def test_update_assignment(self):
        case_id = self._create_case("TXN_UPD_ASSIGN")
        resp = client.patch(f"/cases/{case_id}", json={"assigned_to": "analyst_kumar"})
        assert resp.status_code == 200
        assert resp.json()["assigned_to"] == "analyst_kumar"

    def test_update_findings(self):
        case_id = self._create_case("TXN_UPD_FINDINGS")
        resp = client.patch(f"/cases/{case_id}", json={
            "findings": "Linked to known mule network in Mumbai."
        })
        assert resp.status_code == 200
        assert "mule network" in resp.json()["findings"]

    def test_update_records_events(self):
        case_id = self._create_case("TXN_UPD_EVENTS")
        client.patch(f"/cases/{case_id}", json={"status": "INVESTIGATING"})
        client.patch(f"/cases/{case_id}", json={"assigned_to": "analyst_new"})

        timeline = client.get(f"/cases/{case_id}/timeline").json()
        # CREATED + STATUS_CHANGED + ASSIGNED = 3 events
        assert len(timeline) == 3
        event_types = [e["event_type"] for e in timeline]
        assert "CREATED" in event_types
        assert "STATUS_CHANGED" in event_types
        assert "ASSIGNED" in event_types

    def test_update_invalid_status_rejected(self):
        case_id = self._create_case("TXN_UPD_BAD")
        resp = client.patch(f"/cases/{case_id}", json={"status": "INVALID"})
        assert resp.status_code == 400

    def test_update_nonexistent_case_returns_404(self):
        resp = client.patch("/cases/CASE-fake", json={"status": "OPEN"})
        assert resp.status_code == 404


# ── Add notes ──────────────────────────────────────────────────────────

class TestCaseNotes:

    def _create_case(self, txn_id="TXN_NOTE"):
        alert_id = _ingest_fraud_transaction(txn_id=txn_id)
        resp = client.post("/cases", json={"alert_id": alert_id})
        return resp.json()["case_id"]

    def test_add_note(self):
        case_id = self._create_case("TXN_NOTE_1")
        resp = client.post(f"/cases/{case_id}/notes", json={
            "note": "Contacted the account holder for verification.",
            "actor": "analyst_priya",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["event_type"] == "NOTE_ADDED"
        assert "Contacted" in data["description"]
        assert data["actor"] == "analyst_priya"

    def test_multiple_notes_appear_in_timeline(self):
        case_id = self._create_case("TXN_NOTE_MULTI")
        client.post(f"/cases/{case_id}/notes", json={"note": "Note 1"})
        client.post(f"/cases/{case_id}/notes", json={"note": "Note 2"})

        timeline = client.get(f"/cases/{case_id}/timeline").json()
        note_events = [e for e in timeline if e["event_type"] == "NOTE_ADDED"]
        assert len(note_events) == 2

    def test_add_note_nonexistent_case_returns_404(self):
        resp = client.post("/cases/CASE-fake/notes", json={"note": "test"})
        assert resp.status_code == 404


# ── Close case ─────────────────────────────────────────────────────────

class TestCloseCase:

    def _create_case(self, txn_id="TXN_CLOSE"):
        alert_id = _ingest_fraud_transaction(txn_id=txn_id)
        resp = client.post("/cases", json={"alert_id": alert_id})
        return resp.json()["case_id"], alert_id

    def test_close_as_confirmed_fraud(self):
        case_id, alert_id = self._create_case("TXN_CLOSE_FRAUD")
        resp = client.post(f"/cases/{case_id}/close", json={
            "resolution": "Confirmed fraud. Funds frozen and reported to NPCI.",
            "confirmed_fraud": True,
            "actor": "analyst_ravi",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "CLOSED_CONFIRMED"
        assert data["closed_at"] is not None
        assert "Confirmed fraud" in data["resolution"]

        # Verify alert is RESOLVED
        db = SessionLocal()
        alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
        assert alert.status == "RESOLVED"
        assert alert.resolved_at is not None
        db.close()

    def test_close_as_false_positive(self):
        case_id, alert_id = self._create_case("TXN_CLOSE_FP")
        resp = client.post(f"/cases/{case_id}/close", json={
            "resolution": "False positive. Legitimate high-value transfer.",
            "confirmed_fraud": False,
            "actor": "analyst_priya",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "CLOSED_FALSE_POSITIVE"
        assert data["closed_at"] is not None

        # Verify alert is DISMISSED
        db = SessionLocal()
        alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
        assert alert.status == "DISMISSED"
        assert alert.resolved_at is not None
        db.close()

    def test_close_records_closed_event(self):
        case_id, _ = self._create_case("TXN_CLOSE_EVT")
        client.post(f"/cases/{case_id}/close", json={
            "resolution": "Done.",
            "confirmed_fraud": True,
        })

        timeline = client.get(f"/cases/{case_id}/timeline").json()
        closed_events = [e for e in timeline if e["event_type"] == "CLOSED"]
        assert len(closed_events) == 1
        assert "confirmed fraud" in closed_events[0]["description"]

    def test_close_nonexistent_case_returns_404(self):
        resp = client.post("/cases/CASE-fake/close", json={
            "resolution": "test",
            "confirmed_fraud": True,
        })
        assert resp.status_code == 404


# ── Timeline ───────────────────────────────────────────────────────────

class TestTimeline:

    def test_full_lifecycle_timeline(self):
        """Walk a case through its full lifecycle and verify the timeline."""
        alert_id = _ingest_fraud_transaction(txn_id="TXN_LIFECYCLE")
        create_resp = client.post("/cases", json={
            "alert_id": alert_id,
            "assigned_to": "analyst_a",
        })
        case_id = create_resp.json()["case_id"]

        # Update status
        client.patch(f"/cases/{case_id}", json={"status": "INVESTIGATING"})
        # Add a note
        client.post(f"/cases/{case_id}/notes", json={
            "note": "Reviewing transaction patterns.",
            "actor": "analyst_a",
        })
        # Reassign
        client.patch(f"/cases/{case_id}", json={"assigned_to": "analyst_b"})
        # Close
        client.post(f"/cases/{case_id}/close", json={
            "resolution": "Confirmed mule network activity.",
            "confirmed_fraud": True,
            "actor": "analyst_b",
        })

        timeline = client.get(f"/cases/{case_id}/timeline").json()
        event_types = [e["event_type"] for e in timeline]
        assert event_types == [
            "CREATED",
            "STATUS_CHANGED",
            "NOTE_ADDED",
            "ASSIGNED",
            "CLOSED",
        ]

    def test_timeline_nonexistent_case_returns_404(self):
        resp = client.get("/cases/CASE-fake/timeline")
        assert resp.status_code == 404


# ── Statistics ─────────────────────────────────────────────────────────

class TestCaseStatistics:

    def test_empty_statistics(self):
        resp = client.get("/cases/statistics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cases"] == 0
        assert data["open_cases"] == 0

    def test_statistics_after_case_creation(self):
        for i in range(3):
            alert_id = _ingest_fraud_transaction(
                txn_id=f"TXN_STAT_C{i}",
                sender=f"ACC_SC_S{i}",
                receiver=f"ACC_SC_R{i}",
            )
            client.post("/cases", json={
                "alert_id": alert_id,
                "priority": ["CRITICAL", "HIGH", "MEDIUM"][i],
            })

        resp = client.get("/cases/statistics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_cases"] == 3
        assert data["open_cases"] == 3

    def test_statistics_after_closure(self):
        alert_id = _ingest_fraud_transaction(txn_id="TXN_STAT_CLOSE")
        create_resp = client.post("/cases", json={"alert_id": alert_id})
        case_id = create_resp.json()["case_id"]

        client.post(f"/cases/{case_id}/close", json={
            "resolution": "Confirmed.",
            "confirmed_fraud": True,
        })

        resp = client.get("/cases/statistics")
        data = resp.json()
        assert data["total_cases"] == 1
        assert data["open_cases"] == 0
        assert data["closed_confirmed"] == 1
