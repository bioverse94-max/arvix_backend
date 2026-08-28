"""Fraud case lifecycle service.

Manages the creation, updates, notes, and closure of investigation cases
that are escalated from alerts. Every action is recorded as a CaseEvent
for full audit traceability.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from api.models import Alert, FraudCase, CaseEvent

VALID_CASE_STATUSES = {
    "OPEN", "INVESTIGATING", "ESCALATED",
    "CLOSED_CONFIRMED", "CLOSED_FALSE_POSITIVE",
}
CLOSED_STATUSES = {"CLOSED_CONFIRMED", "CLOSED_FALSE_POSITIVE"}
VALID_PRIORITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def _generate_case_id() -> str:
    return f"CASE-{uuid.uuid4().hex[:8]}"


def _generate_event_id() -> str:
    return f"EVT-{uuid.uuid4().hex[:8]}"


def _add_event(
    db: Session,
    case_id: str,
    event_type: str,
    description: str,
    actor: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
) -> CaseEvent:
    """Record a timeline event on a case."""
    event = CaseEvent(
        event_id=_generate_event_id(),
        case_id=case_id,
        event_type=event_type,
        description=description,
        actor=actor,
        old_value=old_value,
        new_value=new_value,
    )
    db.add(event)
    return event


def create_case(
    alert_id: str,
    db: Session,
    assigned_to: Optional[str] = None,
    priority: str = "MEDIUM",
) -> FraudCase:
    """Create a fraud case from an alert.

    - Validates the alert exists and doesn't already have a case.
    - Sets the alert status to INVESTIGATING.
    - Creates an initial CREATED event.

    Raises ValueError if the alert is not found or already has a case.
    The caller is responsible for commit.
    """
    alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        raise ValueError(f"Alert '{alert_id}' not found")

    # Check if a case already exists for this alert
    existing = db.query(FraudCase).filter(FraudCase.alert_id == alert_id).first()
    if existing:
        raise ValueError(
            f"Alert '{alert_id}' already has case '{existing.case_id}'"
        )

    # Validate priority
    priority_upper = priority.upper()
    if priority_upper not in VALID_PRIORITIES:
        raise ValueError(
            f"Invalid priority '{priority}'. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}"
        )

    # Build case title from alert context
    title = f"Investigation: {alert.title}"

    case = FraudCase(
        case_id=_generate_case_id(),
        alert_id=alert_id,
        title=title,
        description=alert.description,
        status="OPEN",
        priority=priority_upper,
        assigned_to=assigned_to,
    )
    db.add(case)

    # Update alert status to INVESTIGATING
    alert.status = "INVESTIGATING"

    # Record the CREATED event
    desc_parts = [f"Case created from alert {alert_id}."]
    if assigned_to:
        desc_parts.append(f"Assigned to {assigned_to}.")
    _add_event(
        db,
        case.case_id,
        event_type="CREATED",
        description=" ".join(desc_parts),
        actor=assigned_to,
        new_value="OPEN",
    )

    return case


def update_case(
    case_id: str,
    db: Session,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    findings: Optional[str] = None,
    actor: Optional[str] = None,
) -> FraudCase:
    """Update a fraud case and record events for each change.

    Raises ValueError for invalid inputs. KeyError if case not found.
    The caller is responsible for commit.
    """
    case = db.query(FraudCase).filter(FraudCase.case_id == case_id).first()
    if not case:
        raise KeyError(f"Case '{case_id}' not found")

    if status is not None:
        new_status = status.upper()
        if new_status not in VALID_CASE_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of: "
                f"{', '.join(sorted(VALID_CASE_STATUSES))}"
            )
        if new_status != case.status:
            old_status = case.status
            case.status = new_status
            _add_event(
                db, case_id,
                event_type="STATUS_CHANGED",
                description=f"Status changed from {old_status} to {new_status}.",
                actor=actor,
                old_value=old_status,
                new_value=new_status,
            )
            # Handle closure
            if new_status in CLOSED_STATUSES:
                case.closed_at = datetime.now(timezone.utc)
            else:
                case.closed_at = None

    if priority is not None:
        new_priority = priority.upper()
        if new_priority not in VALID_PRIORITIES:
            raise ValueError(
                f"Invalid priority '{priority}'. Must be one of: "
                f"{', '.join(sorted(VALID_PRIORITIES))}"
            )
        if new_priority != case.priority:
            old_priority = case.priority
            case.priority = new_priority
            _add_event(
                db, case_id,
                event_type="STATUS_CHANGED",
                description=f"Priority changed from {old_priority} to {new_priority}.",
                actor=actor,
                old_value=old_priority,
                new_value=new_priority,
            )

    if assigned_to is not None and assigned_to != case.assigned_to:
        old_assigned = case.assigned_to
        case.assigned_to = assigned_to
        _add_event(
            db, case_id,
            event_type="ASSIGNED",
            description=f"Case reassigned from {old_assigned or 'unassigned'} to {assigned_to}.",
            actor=actor,
            old_value=old_assigned,
            new_value=assigned_to,
        )

    if findings is not None:
        case.findings = findings
        _add_event(
            db, case_id,
            event_type="NOTE_ADDED",
            description=f"Findings updated.",
            actor=actor,
            new_value=findings[:200] if findings else None,  # Truncate for event
        )

    return case


def add_case_note(
    case_id: str,
    note: str,
    db: Session,
    actor: Optional[str] = None,
) -> CaseEvent:
    """Add an investigation note to a case.

    Raises KeyError if case not found. Caller is responsible for commit.
    """
    case = db.query(FraudCase).filter(FraudCase.case_id == case_id).first()
    if not case:
        raise KeyError(f"Case '{case_id}' not found")

    event = _add_event(
        db, case_id,
        event_type="NOTE_ADDED",
        description=note,
        actor=actor,
    )
    return event


def close_case(
    case_id: str,
    resolution: str,
    confirmed_fraud: bool,
    db: Session,
    actor: Optional[str] = None,
) -> FraudCase:
    """Close a fraud case and sync the linked alert.

    If confirmed_fraud=True → status=CLOSED_CONFIRMED, alert→RESOLVED.
    If confirmed_fraud=False → status=CLOSED_FALSE_POSITIVE, alert→DISMISSED.

    Raises KeyError if case not found. Caller is responsible for commit.
    """
    case = db.query(FraudCase).filter(FraudCase.case_id == case_id).first()
    if not case:
        raise KeyError(f"Case '{case_id}' not found")

    old_status = case.status
    if confirmed_fraud:
        case.status = "CLOSED_CONFIRMED"
        alert_status = "RESOLVED"
    else:
        case.status = "CLOSED_FALSE_POSITIVE"
        alert_status = "DISMISSED"

    case.resolution = resolution
    case.closed_at = datetime.now(timezone.utc)

    # Sync the linked alert
    alert = db.query(Alert).filter(Alert.alert_id == case.alert_id).first()
    if alert:
        alert.status = alert_status
        alert.resolution_notes = resolution
        alert.resolved_at = datetime.now(timezone.utc)

    _add_event(
        db, case_id,
        event_type="CLOSED",
        description=(
            f"Case closed as {'confirmed fraud' if confirmed_fraud else 'false positive'}. "
            f"Resolution: {resolution}"
        ),
        actor=actor,
        old_value=old_status,
        new_value=case.status,
    )

    return case


def get_case_statistics(db: Session) -> dict:
    """Return aggregated case counts for the dashboard."""
    total = db.query(FraudCase).count()

    status_counts = (
        db.query(FraudCase.status, sa_func.count(FraudCase.case_id))
        .group_by(FraudCase.status)
        .all()
    )
    status_map = {s: c for s, c in status_counts}

    priority_counts = (
        db.query(FraudCase.priority, sa_func.count(FraudCase.case_id))
        .group_by(FraudCase.priority)
        .all()
    )

    return {
        "total_cases": total,
        "open_cases": status_map.get("OPEN", 0),
        "investigating_cases": status_map.get("INVESTIGATING", 0),
        "escalated_cases": status_map.get("ESCALATED", 0),
        "closed_confirmed": status_map.get("CLOSED_CONFIRMED", 0),
        "closed_false_positive": status_map.get("CLOSED_FALSE_POSITIVE", 0),
        "by_priority": [{"severity": p, "count": c} for p, c in priority_counts],
        "by_status": [{"status": s, "count": c} for s, c in status_counts],
    }
