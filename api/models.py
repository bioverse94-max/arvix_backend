from sqlalchemy import Column, String, DateTime, Integer, Numeric, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from api.database import Base

class Account(Base):
    __tablename__ = "accounts"

    account_id = Column(String, primary_key=True, index=True)
    vpa = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    kyc_tier = Column(String, nullable=True)
    account_age_days = Column(Integer, nullable=True)
    current_risk_tier = Column(String, nullable=True)
    
    # Flag to clearly identify this as a stub record created during ingestion
    is_stub = Column(Boolean, default=False, nullable=False)

class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(String, primary_key=True, index=True)
    sender_account_id = Column(String, ForeignKey("accounts.account_id"), nullable=False)
    receiver_account_id = Column(String, ForeignKey("accounts.account_id"), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    sender = relationship("Account", foreign_keys=[sender_account_id])
    receiver = relationship("Account", foreign_keys=[receiver_account_id])
    alerts = relationship("Alert", back_populates="transaction")
    fraud_result = relationship("FraudResult", back_populates="transaction", uselist=False)


class FraudResult(Base):
    __tablename__ = "fraud_results"

    result_id = Column(String, primary_key=True, index=True)
    transaction_id = Column(String, ForeignKey("transactions.transaction_id"), nullable=False, unique=True)

    pol_score = Column(Numeric(5, 4), nullable=True)       # Pattern-of-Life anomaly score (0-1)
    graph_score = Column(Numeric(5, 4), nullable=True)     # Graph anomaly score (0-1)
    final_risk_score = Column(Numeric(5, 4), nullable=True) # Fused risk score (0-1)
    risk_level = Column(String, nullable=True)              # CRITICAL, HIGH, MEDIUM, LOW
    risk_flag = Column(Boolean, default=False, nullable=False)  # Score exceeds threshold

    fraud_reasons = Column(Text, nullable=True)             # JSON array of explanations
    model_version = Column(String, nullable=True)           # e.g. "pol_v1+graph_v1+fusion_v1"
    pol_features = Column(Text, nullable=True)              # JSON of PoL feature values
    graph_features = Column(Text, nullable=True)            # JSON of graph feature values

    scored_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    transaction = relationship("Transaction", back_populates="fraud_result")




class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(String, primary_key=True, index=True)
    transaction_id = Column(String, ForeignKey("transactions.transaction_id"), nullable=False)

    alert_type = Column(String, nullable=False)       # FRAUD_DETECTED, SUSPICIOUS_PATTERN, HIGH_RISK_SCORE
    severity = Column(String, nullable=False)          # CRITICAL, HIGH, MEDIUM
    status = Column(String, nullable=False, default="OPEN")  # OPEN, ACKNOWLEDGED, INVESTIGATING, RESOLVED, DISMISSED

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    fraud_scenario = Column(String, nullable=True)
    risk_score = Column(Numeric(5, 2), nullable=True)  # Placeholder for future risk engine

    assigned_to = Column(String, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    transaction = relationship("Transaction", back_populates="alerts")
    fraud_case = relationship("FraudCase", back_populates="alert", uselist=False)


class FraudCase(Base):
    __tablename__ = "fraud_cases"

    case_id = Column(String, primary_key=True, index=True)
    alert_id = Column(String, ForeignKey("alerts.alert_id"), nullable=False, unique=True)

    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="OPEN")
    # OPEN, INVESTIGATING, ESCALATED, CLOSED_CONFIRMED, CLOSED_FALSE_POSITIVE
    priority = Column(String, nullable=False, default="MEDIUM")
    # CRITICAL, HIGH, MEDIUM, LOW

    assigned_to = Column(String, nullable=True)
    findings = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    alert = relationship("Alert", back_populates="fraud_case")
    events = relationship("CaseEvent", back_populates="case", order_by="CaseEvent.created_at")


class CaseEvent(Base):
    __tablename__ = "case_events"

    event_id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("fraud_cases.case_id"), nullable=False)

    event_type = Column(String, nullable=False)
    # CREATED, STATUS_CHANGED, ASSIGNED, NOTE_ADDED, ESCALATED, CLOSED
    description = Column(Text, nullable=False)
    actor = Column(String, nullable=True)
    old_value = Column(String, nullable=True)
    new_value = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    case = relationship("FraudCase", back_populates="events")


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=False)
    role = Column(String, nullable=False, default="ANALYST")  # ADMIN, ANALYST, PARTNER_BANK, AUDITOR
    partner_bank = Column(String, nullable=True)             # e.g., HDFC Bank, ICICI Bank, SBI, NPCI Central Switch
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True, nullable=False)
    actor_id = Column(String, nullable=True)
    actor_name = Column(String, nullable=True)
    actor_role = Column(String, nullable=True)
    action_type = Column(String, nullable=False)  # LOGIN, REGISTER, FREEZE_ACCOUNT, STEP_UP_REQUEST, ASSIGN_CASE, ESCALATE_CASE, RESOLVE_CASE, CONFIG_CHANGE, SCORE_TRANSACTIONS, UPDATE_ALERT
    target_id = Column(String, nullable=True)
    target_type = Column(String, nullable=True)  # ACCOUNT, TRANSACTION, CASE, ALERT, USER, SYSTEM
    ip_address = Column(String, nullable=True)
    details = Column(Text, nullable=True)
    auth_confirmed = Column(Boolean, default=True, nullable=False)

