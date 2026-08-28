"""Tests for Authentication, Partner Login, Role-Based Access Control (RBAC), and Audit Logs.

Covers:
- Salted PBKDF2 password hashing & verification
- JWT Token creation, expiration, and validation
- User and Partner registration and duplicate rejection
- User login flow and token issuance
- GET /auth/me profile and active role permissions
- POST /auth/seed demo accounts
- Audit log persistence, automated hook recording, and querying
"""
import json
import uuid
import pytest
from datetime import timedelta
from fastapi.testclient import TestClient

from api.main import app
from api.database import SessionLocal
from api.models import User, AuditLog, Alert, FraudCase, CaseEvent, FraudResult, Transaction, Account
from api import security
from api import audit_service

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db():
    """Clean all tables before each test for isolated execution."""
    db = SessionLocal()
    db.query(AuditLog).delete()
    db.query(User).delete()
    db.query(CaseEvent).delete()
    db.query(FraudCase).delete()
    db.query(FraudResult).delete()
    db.query(Alert).delete()
    db.query(Transaction).delete()
    db.query(Account).delete()
    db.commit()
    db.close()
    yield


# ── 1. Security & Cryptographic Primitives ─────────────────────────────

class TestSecurityPrimitives:

    def test_password_hashing_and_verification(self):
        password = "SecurePassword123!"
        hashed = security.hash_password(password)

        assert hashed != password
        assert "$" in hashed
        assert security.verify_password(password, hashed) is True
        assert security.verify_password("WrongPassword", hashed) is False

    def test_jwt_token_generation_and_decode(self):
        user = User(
            user_id="USR_TEST_01",
            email="test@npci.gov.in",
            hashed_password="hash",
            full_name="Test Specialist",
            role="ANALYST",
            partner_bank="NPCI Central Switch",
            is_active=True,
        )
        token = security.create_access_token(user)
        assert isinstance(token, str)
        assert len(token) > 20

        payload = security.decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "USR_TEST_01"
        assert payload["email"] == "test@npci.gov.in"
        assert payload["role"] == "ANALYST"
        assert payload["partner_bank"] == "NPCI Central Switch"

    def test_expired_token_returns_none(self):
        user = User(
            user_id="USR_EXP",
            email="exp@npci.gov.in",
            hashed_password="hash",
            full_name="Expired User",
            role="ANALYST",
        )
        # Token expired 1 hour ago
        expired_token = security.create_access_token(user, expires_delta=timedelta(hours=-1))
        payload = security.decode_access_token(expired_token)
        assert payload is None


# ── 2. User & Partner Registration & Login ─────────────────────────────

class TestUserAuthFlows:

    def test_register_user_success(self):
        payload = {
            "email": "analyst.priya@npci.gov.in",
            "password": "mypassword123",
            "full_name": "Priya Sharma",
            "role": "ANALYST",
            "partner_bank": "NPCI Central Switch",
        }
        resp = client.post("/auth/register", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "analyst.priya@npci.gov.in"
        assert data["full_name"] == "Priya Sharma"
        assert data["role"] == "ANALYST"
        assert "alerts:read" in data["permissions"]

        # Verify in DB
        db = SessionLocal()
        user = db.query(User).filter(User.email == "analyst.priya@npci.gov.in").first()
        assert user is not None
        assert security.verify_password("mypassword123", user.hashed_password) is True
        db.close()

    def test_register_duplicate_email_rejected(self):
        payload = {
            "email": "duplicate@npci.gov.in",
            "password": "password123",
            "full_name": "First User",
            "role": "ANALYST",
        }
        resp1 = client.post("/auth/register", json=payload)
        assert resp1.status_code == 200

        # Second registration with same email
        resp2 = client.post("/auth/register", json=payload)
        assert resp2.status_code == 400
        assert "already exists" in resp2.json()["detail"]

    def test_register_invalid_role_rejected(self):
        payload = {
            "email": "invalid.role@npci.gov.in",
            "password": "password123",
            "full_name": "Bad Role User",
            "role": "SUPER_HACKER",
        }
        resp = client.post("/auth/register", json=payload)
        assert resp.status_code == 400
        assert "Invalid role" in resp.json()["detail"]

    def test_login_success(self):
        # Register user
        reg_payload = {
            "email": "officer@hdfcbank.com",
            "password": "HdfcSecurityKey2026",
            "full_name": "Rajesh Nair",
            "role": "PARTNER_BANK",
            "partner_bank": "HDFC Bank",
        }
        client.post("/auth/register", json=reg_payload)

        # Login
        login_payload = {
            "email": "officer@hdfcbank.com",
            "password": "HdfcSecurityKey2026",
        }
        resp = client.post("/auth/login", json=login_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "officer@hdfcbank.com"
        assert data["user"]["role"] == "PARTNER_BANK"
        assert data["user"]["partner_bank"] == "HDFC Bank"

    def test_login_invalid_password_returns_401(self):
        reg_payload = {
            "email": "valid@npci.gov.in",
            "password": "correct_password",
            "full_name": "Valid User",
            "role": "ANALYST",
        }
        client.post("/auth/register", json=reg_payload)

        resp = client.post("/auth/login", json={"email": "valid@npci.gov.in", "password": "wrong_password"})
        assert resp.status_code == 401
        assert "Invalid credentials" in resp.json()["detail"]

    def test_login_nonexistent_user_returns_401(self):
        resp = client.post("/auth/login", json={"email": "ghost@npci.gov.in", "password": "any"})
        assert resp.status_code == 401

    def test_seed_demo_users_endpoint(self):
        resp = client.post("/auth/seed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["created_count"] >= 4

        # Verify analyst can log in immediately
        login_resp = client.post("/auth/login", json={"email": "analyst@npci.gov.in", "password": "password123"})
        assert login_resp.status_code == 200
        assert login_resp.json()["user"]["role"] == "ANALYST"


# ── 3. Protected Profile & RBAC Permissions ───────────────────────────

class TestProfileAndRBAC:

    def _get_auth_header(self, email="analyst@npci.gov.in", password="password123", role="ANALYST", bank="NPCI"):
        client.post("/auth/register", json={
            "email": email,
            "password": password,
            "full_name": f"{role} User",
            "role": role,
            "partner_bank": bank,
        })
        login_resp = client.post("/auth/login", json={"email": email, "password": password})
        token = login_resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def test_get_current_user_profile(self):
        headers = self._get_auth_header(email="analyst.me@npci.gov.in", role="ANALYST")
        resp = client.get("/auth/me", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["email"] == "analyst.me@npci.gov.in"
        assert data["role"] == "ANALYST"
        assert "cases:write" in data["permissions"]

    def test_get_current_user_without_token_returns_401(self):
        resp = client.get("/auth/me")
        assert resp.status_code == 401

    def test_role_permissions_matrix(self):
        admin_perms = security.get_permissions_for_role("ADMIN")
        assert "admin:all" in admin_perms

        analyst_perms = security.get_permissions_for_role("ANALYST")
        assert "cases:write" in analyst_perms
        assert "audit:read" in analyst_perms

        partner_perms = security.get_permissions_for_role("PARTNER_BANK")
        assert "alerts:read" in partner_perms
        assert "models:score" not in partner_perms

        auditor_perms = security.get_permissions_for_role("AUDITOR")
        assert "audit:read" in auditor_perms
        assert "cases:write" not in auditor_perms


# ── 4. Compliance Audit Logs ──────────────────────────────────────────

class TestAuditLogs:

    def test_create_and_list_audit_logs(self):
        # Manually create audit entry
        create_payload = {
            "action_type": "FREEZE_ACCOUNT",
            "target_type": "ACCOUNT",
            "target_id": "ACC_MULE_9988",
            "details": "Emergency account freeze executed following high-velocity circular flow detection",
        }
        resp = client.post("/audit-logs", json=create_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action_type"] == "FREEZE_ACCOUNT"
        assert data["target_id"] == "ACC_MULE_9988"
        assert "AUD-" in data["log_id"]

        # List logs
        list_resp = client.get("/audit-logs")
        assert list_resp.status_code == 200
        logs_data = list_resp.json()
        assert logs_data["total"] >= 1
        assert logs_data["logs"][0]["action_type"] == "FREEZE_ACCOUNT"

    def test_filter_audit_logs_by_action_type(self):
        client.post("/audit-logs", json={"action_type": "FREEZE_ACCOUNT", "target_id": "ACC_1"})
        client.post("/audit-logs", json={"action_type": "STEP_UP_REQUEST", "target_id": "ACC_2"})

        resp = client.get("/audit-logs", params={"action_type": "FREEZE_ACCOUNT"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 1
        assert resp.json()["logs"][0]["action_type"] == "FREEZE_ACCOUNT"

    def test_automatic_audit_log_on_login(self):
        # Register and login
        client.post("/auth/register", json={
            "email": "audited.analyst@npci.gov.in",
            "password": "password123",
            "full_name": "Audited Analyst",
            "role": "ANALYST",
        })
        client.post("/auth/login", json={"email": "audited.analyst@npci.gov.in", "password": "password123"})

        # Check audit log contains LOGIN
        resp = client.get("/audit-logs", params={"action_type": "LOGIN"})
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1
        assert resp.json()["logs"][0]["actor_name"] == "Audited Analyst"

    def test_automatic_audit_log_on_case_creation(self):
        # Ingest fraudulent txn to generate alert
        txn_id = f"TXN_{uuid.uuid4().hex[:8]}"
        client.post("/transactions", json={
            "transaction_id": txn_id,
            "utr": f"UTR_{txn_id}",
            "timestamp": "2026-08-28T12:00:00Z",
            "sender_vpa": "s@upi",
            "sender_account_id": "ACC_S",
            "receiver_vpa": "r@upi",
            "receiver_account_id": "ACC_R",
            "amount": 20000.0,
            "currency": "INR",
            "transaction_type": "P2P",
            "channel": "UPI",
            "status": "SUCCESS",
            "is_fraud": True,
        })
        alerts = client.get("/alerts").json()["alerts"]
        assert len(alerts) >= 1
        alert_id = alerts[0]["alert_id"]

        # Create case from alert
        client.post("/cases", json={"alert_id": alert_id, "priority": "HIGH", "assigned_to": "Analyst Priya"})

        # Verify audit log captured CREATE_CASE / ASSIGN_CASE
        resp = client.get("/audit-logs", params={"target_type": "CASE"})
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1
