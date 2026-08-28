"""Alert generation service.

Evaluates incoming transactions and creates alerts for fraudulent ones.
Currently uses the ground-truth `is_fraud` label as the trigger — once the
risk engine (Parts 3-5) is built, this will switch to using the computed
risk score instead.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from api.models import Alert

# Severity mapping by fraud scenario.
# account_takeover → CRITICAL (direct financial loss, compromised credentials)
# mule_network, circular_flow → HIGH (organized fraud patterns)
# Everything else → MEDIUM
SEVERITY_MAP = {
    "account_takeover": "CRITICAL",
    "mule_network": "HIGH",
    "circular_flow": "HIGH",
    "fan_in": "MEDIUM",
    "fan_out": "MEDIUM",
    "rapid_pass_through": "MEDIUM",
}

# Human-readable titles per scenario
SCENARIO_TITLES = {
    "account_takeover": "Account Takeover Detected",
    "mule_network": "Mule Network Activity",
    "circular_flow": "Circular Fund Flow Detected",
    "fan_in": "Fan-In Pattern Detected",
    "fan_out": "Fan-Out Pattern Detected",
    "rapid_pass_through": "Rapid Pass-Through Detected",
}

SCENARIO_DESCRIPTIONS = {
    "account_takeover": (
        "A transaction from a potentially compromised account has been detected. "
        "The account may have been accessed by an unauthorized party using a new device or IP."
    ),
    "mule_network": (
        "Funds are being relayed through a chain of accounts, each keeping a small cut. "
        "This pattern is consistent with money mule activity."
    ),
    "circular_flow": (
        "Funds have been detected flowing in a circular pattern back to the originating "
        "account, potentially indicating layering or round-tripping."
    ),
    "fan_in": (
        "Multiple senders are transferring funds to a single collector account. "
        "This concentration pattern may indicate illegal fund aggregation."
    ),
    "fan_out": (
        "A single account is distributing funds to many receivers with amounts kept "
        "below reporting thresholds, potentially indicating smurfing or structuring."
    ),
    "rapid_pass_through": (
        "Funds received into an account were immediately transferred out within minutes, "
        "suggesting the account is being used as a pass-through."
    ),
}

VALID_STATUSES = {"OPEN", "ACKNOWLEDGED", "INVESTIGATING", "RESOLVED", "DISMISSED"}
TERMINAL_STATUSES = {"RESOLVED", "DISMISSED"}


def _generate_alert_id() -> str:
    """Generate a unique alert ID like ALT-a1b2c3d4."""
    return f"ALT-{uuid.uuid4().hex[:8]}"


def evaluate_transaction(transaction: dict) -> bool:
    """Decide whether a transaction should generate an alert.

    Current logic: alert if is_fraud is True.
    Future: use risk score from the risk engine when Parts 3-5 are built.
    """
    return bool(transaction.get("is_fraud", False))


def create_alert(transaction: dict, db: Session) -> Alert:
    """Build and persist an Alert record for a fraudulent transaction.

    Args:
        transaction: The raw transaction dict (as received by the ingestion API).
        db: An active SQLAlchemy session — caller is responsible for commit.

    Returns:
        The created Alert instance.
    """
    scenario = transaction.get("fraud_scenario") or "unknown"
    amount = transaction.get("amount", 0)
    severity = SEVERITY_MAP.get(scenario, "MEDIUM")
    base_title = SCENARIO_TITLES.get(scenario, "Suspicious Transaction Detected")
    title = f"{base_title} — ₹{amount:,.2f}"
    description = SCENARIO_DESCRIPTIONS.get(
        scenario,
        f"A suspicious transaction has been flagged for review. Scenario: {scenario}."
    )

    alert = Alert(
        alert_id=_generate_alert_id(),
        transaction_id=transaction["transaction_id"],
        alert_type="FRAUD_DETECTED",
        severity=severity,
        status="OPEN",
        title=title,
        description=description,
        fraud_scenario=scenario if scenario != "unknown" else None,
        risk_score=None,  # Placeholder for future risk engine
        assigned_to=None,
        resolution_notes=None,
        resolved_at=None,
    )
    db.add(alert)
    return alert


def get_alert_statistics(db: Session) -> dict:
    """Return aggregated alert counts for the dashboard.

    Returns a dict with total, per-status counts, and per-severity counts.
    """
    total = db.query(Alert).count()

    status_counts = (
        db.query(Alert.status, sa_func.count(Alert.alert_id))
        .group_by(Alert.status)
        .all()
    )
    status_map = {s: c for s, c in status_counts}

    severity_counts = (
        db.query(Alert.severity, sa_func.count(Alert.alert_id))
        .group_by(Alert.severity)
        .all()
    )

    return {
        "total_alerts": total,
        "open_alerts": status_map.get("OPEN", 0),
        "acknowledged_alerts": status_map.get("ACKNOWLEDGED", 0),
        "investigating_alerts": status_map.get("INVESTIGATING", 0),
        "resolved_alerts": status_map.get("RESOLVED", 0),
        "dismissed_alerts": status_map.get("DISMISSED", 0),
        "by_severity": [{"severity": s, "count": c} for s, c in severity_counts],
        "by_status": [{"status": s, "count": c} for s, c in status_counts],
    }
