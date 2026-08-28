"""Audit logging service — records immutable compliance and intervention actions.

Tracks:
- Analyst case assignments, escalations, closures, and note additions.
- Switch-level alert updates and account status changes (e.g. Freezes, Step-ups).
- User authentication events (Logins, Registration, Role updates).
- Real-time and batch ML scoring execution runs.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import or_

from api.models import AuditLog, User


def record_audit_log(
    db: Session,
    action_type: str,
    actor_id: Optional[str] = None,
    actor_name: Optional[str] = None,
    actor_role: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[Any] = None,
    ip_address: Optional[str] = None,
    auth_confirmed: bool = True,
) -> AuditLog:
    """Create and persist an immutable AuditLog record in the database."""
    # Serialize details if dictionary or object
    details_str = details
    if isinstance(details, (dict, list)):
        details_str = json.dumps(details)

    log_entry = AuditLog(
        log_id=f"AUD-{uuid.uuid4().hex[:10].upper()}",
        timestamp=datetime.now(timezone.utc),
        actor_id=actor_id or "SYSTEM",
        actor_name=actor_name or "Automated Switch Rule",
        actor_role=actor_role or "SYSTEM_DAEMON",
        action_type=action_type,
        target_id=target_id,
        target_type=target_type,
        ip_address=ip_address or "127.0.0.1",
        details=details_str,
        auth_confirmed=auth_confirmed,
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    return log_entry


def list_audit_logs(
    db: Session,
    action_type: Optional[str] = None,
    target_type: Optional[str] = None,
    actor_name: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[AuditLog], int]:
    """Query audit logs with optional filters and pagination. Returns (logs, total_count)."""
    query = db.query(AuditLog)

    if action_type:
        query = query.filter(AuditLog.action_type == action_type.upper())

    if target_type:
        query = query.filter(AuditLog.target_type == target_type.upper())

    if actor_name:
        query = query.filter(AuditLog.actor_name.ilike(f"%{actor_name}%"))

    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                AuditLog.log_id.ilike(search_term),
                AuditLog.actor_name.ilike(search_term),
                AuditLog.target_id.ilike(search_term),
                AuditLog.details.ilike(search_term),
                AuditLog.action_type.ilike(search_term),
            )
        )

    total = query.count()
    logs = (
        query
        .order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return logs, total


def log_login_event(
    db: Session,
    user: User,
    ip_address: Optional[str] = None,
    auth_confirmed: bool = True,
) -> AuditLog:
    """Helper to record a user/partner login event."""
    return record_audit_log(
        db=db,
        action_type="LOGIN",
        actor_id=user.user_id,
        actor_name=user.full_name,
        actor_role=user.role,
        target_type="USER",
        target_id=user.user_id,
        details=f"User authenticated successfully via JWT session. Partner: {user.partner_bank or 'NPCI Central'}",
        ip_address=ip_address,
        auth_confirmed=auth_confirmed,
    )
