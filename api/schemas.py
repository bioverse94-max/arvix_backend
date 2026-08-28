"""Pydantic schemas for alert and fraud case API request/response models."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Alert schemas ──────────────────────────────────────────────────────

class AlertResponse(BaseModel):
    """Serializes a single alert for API responses."""
    model_config = ConfigDict(from_attributes=True)

    alert_id: str
    transaction_id: str
    alert_type: str
    severity: str
    status: str
    title: str
    description: Optional[str] = None
    fraud_scenario: Optional[str] = None
    risk_score: Optional[float] = None
    assigned_to: Optional[str] = None
    resolution_notes: Optional[str] = None
    sender_account_id: Optional[str] = None
    sender_vpa: Optional[str] = None
    receiver_account_id: Optional[str] = None
    receiver_vpa: Optional[str] = None
    amount: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None


class AlertListResponse(BaseModel):
    """Paginated list of alerts."""
    alerts: List[AlertResponse]
    total: int
    page: int
    page_size: int


class AlertUpdateRequest(BaseModel):
    """Request body for PATCH /alerts/{alert_id}."""
    status: Optional[str] = Field(
        None,
        description="New status: OPEN, ACKNOWLEDGED, INVESTIGATING, RESOLVED, DISMISSED"
    )
    assigned_to: Optional[str] = Field(None, description="Analyst to assign the alert to")
    resolution_notes: Optional[str] = Field(None, description="Notes when resolving/dismissing")


class SeverityCount(BaseModel):
    severity: str
    count: int


class StatusCount(BaseModel):
    status: str
    count: int


class AlertStatisticsResponse(BaseModel):
    """Aggregated alert counts for the dashboard."""
    total_alerts: int
    open_alerts: int
    acknowledged_alerts: int
    investigating_alerts: int
    resolved_alerts: int
    dismissed_alerts: int
    by_severity: List[SeverityCount]
    by_status: List[StatusCount]


# ── Fraud Case schemas ─────────────────────────────────────────────────

class CaseEventResponse(BaseModel):
    """A single timeline event on a fraud case."""
    model_config = ConfigDict(from_attributes=True)

    event_id: str
    case_id: str
    event_type: str
    description: str
    actor: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    created_at: datetime


class CaseResponse(BaseModel):
    """Full fraud case with nested alert info and event timeline."""
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    alert_id: str
    title: str
    description: Optional[str] = None
    status: str
    priority: str
    assigned_to: Optional[str] = None
    findings: Optional[str] = None
    resolution: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None
    alert: Optional[AlertResponse] = None
    events: List[CaseEventResponse] = []


class CaseListResponse(BaseModel):
    """Paginated list of fraud cases."""
    cases: List[CaseResponse]
    total: int
    page: int
    page_size: int


class CaseCreateRequest(BaseModel):
    """Request body for POST /cases."""
    alert_id: str = Field(..., description="The alert to escalate into a case")
    assigned_to: Optional[str] = Field(None, description="Analyst to assign")
    priority: Optional[str] = Field("MEDIUM", description="CRITICAL, HIGH, MEDIUM, LOW")


class CaseUpdateRequest(BaseModel):
    """Request body for PATCH /cases/{case_id}."""
    status: Optional[str] = Field(
        None,
        description="OPEN, INVESTIGATING, ESCALATED, CLOSED_CONFIRMED, CLOSED_FALSE_POSITIVE"
    )
    priority: Optional[str] = Field(None, description="CRITICAL, HIGH, MEDIUM, LOW")
    assigned_to: Optional[str] = Field(None, description="Analyst to assign")
    findings: Optional[str] = Field(None, description="Investigation findings")


class CaseNoteRequest(BaseModel):
    """Request body for POST /cases/{case_id}/notes."""
    note: str = Field(..., description="The investigation note text")
    actor: Optional[str] = Field(None, description="Who is adding the note")


class CaseCloseRequest(BaseModel):
    """Request body for POST /cases/{case_id}/close."""
    resolution: str = Field(..., description="Resolution summary")
    confirmed_fraud: bool = Field(..., description="True = confirmed fraud, False = false positive")
    actor: Optional[str] = Field(None, description="Who is closing the case")


class CaseStatisticsResponse(BaseModel):
    """Aggregated fraud case counts for the dashboard."""
    total_cases: int
    open_cases: int
    investigating_cases: int
    escalated_cases: int
    closed_confirmed: int
    closed_false_positive: int
    by_priority: List[SeverityCount]  # reuse SeverityCount shape (label + count)
    by_status: List[StatusCount]


# ── Fraud Result schemas ───────────────────────────────────────────────

class FraudResultResponse(BaseModel):
    """ML scoring result for a single transaction."""
    model_config = ConfigDict(from_attributes=True)

    result_id: str
    transaction_id: str
    pol_score: Optional[float] = None
    graph_score: Optional[float] = None
    final_risk_score: Optional[float] = None
    risk_level: Optional[str] = None
    risk_flag: bool = False
    fraud_reasons: Optional[str] = None      # JSON string
    model_version: Optional[str] = None
    pol_features: Optional[str] = None       # JSON string
    graph_features: Optional[str] = None     # JSON string
    scored_at: datetime


class FraudResultListResponse(BaseModel):
    """Paginated list of fraud results."""
    results: List[FraudResultResponse]
    total: int
    page: int
    page_size: int


class BatchScoringRequest(BaseModel):
    """Request body for POST /scoring/batch."""
    transaction_ids: Optional[List[str]] = Field(
        None, description="Specific transaction IDs to score. If omitted, scores all unscored."
    )


class BatchScoringResponse(BaseModel):
    """Response from batch scoring."""
    scored: int
    stored: int
    message: str


# ── Transaction & Dashboard schemas ────────────────────────────────────

class TransactionResponse(BaseModel):
    """Serializes a single transaction for API responses with attached ML scores."""
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    sender_account_id: str
    receiver_account_id: str
    amount: float
    timestamp: datetime
    status: str
    created_at: datetime

    # Attached ML scoring fields
    risk_score: Optional[float] = None
    risk_level: Optional[str] = None
    is_fraud: Optional[bool] = False
    pol_anomaly_score: Optional[float] = None
    graph_anomaly_score: Optional[float] = None
    fraud_reasons: Optional[List[str]] = None


class GenerateSyntheticRequest(BaseModel):
    """Request schema for dynamic synthetic dataset generation."""
    num_accounts: Optional[int] = Field(100, ge=10, le=5000)
    num_transactions: Optional[int] = Field(200, ge=10, le=20000)
    scenarios: Optional[List[str]] = Field(["mule_network", "account_takeover", "circular_flow"])
    seed: Optional[int] = 42
    reset_db: Optional[bool] = False


class GenerateSyntheticResponse(BaseModel):
    """Response schema from dynamic synthetic generation."""
    status: str
    generated_transactions: int
    inserted_transactions: int
    ml_scores_computed: int
    alerts_created: int
    scenarios_injected: List[str]


class TransactionListResponse(BaseModel):
    """Paginated list of transactions."""
    transactions: List[TransactionResponse]
    total: int
    page: int
    page_size: int


class DashboardStatsResponse(BaseModel):
    """Aggregated dashboard statistics."""
    total_transactions: int
    total_alerts: int
    open_alerts: int
    critical_alerts: int
    total_cases: int
    open_cases: int
    total_fraud_scored: int
    high_risk_scored: int


# ── Authentication & RBAC schemas ──────────────────────────────────────

class UserRegisterRequest(BaseModel):
    """Payload to register a new user or partner."""
    email: str = Field(..., description="User's email address or operator ID")
    password: str = Field(..., min_length=6, description="Plaintext password")
    full_name: str = Field(..., description="Full name of user")
    role: str = Field("ANALYST", description="ADMIN, ANALYST, PARTNER_BANK, AUDITOR")
    partner_bank: Optional[str] = Field(None, description="Bank affiliation e.g. HDFC Bank, ICICI Bank")


class UserLoginRequest(BaseModel):
    """Payload for user / partner login."""
    email: str
    password: str


class UserResponse(BaseModel):
    """Public user identity and permissions profile."""
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    email: str
    full_name: str
    role: str
    partner_bank: Optional[str] = None
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None
    permissions: List[str] = []


class TokenResponse(BaseModel):
    """JWT bearer token and user summary returned on login."""
    access_token: str
    token_type: str = "bearer"
    expires_in_hours: int = 24
    user: UserResponse


class SeedDemoUsersResponse(BaseModel):
    """Summary of demo accounts created."""
    created_count: int
    accounts: List[UserResponse]


# ── Audit Log schemas ──────────────────────────────────────────────────

class AuditLogCreateRequest(BaseModel):
    """Manual audit intervention log creation."""
    action_type: str = Field(..., description="Action executed e.g. FREEZE_ACCOUNT, STEP_UP_REQUEST, NOTE_ADDED")
    target_type: Optional[str] = Field(None, description="ACCOUNT, TRANSACTION, CASE, ALERT, USER, SYSTEM")
    target_id: Optional[str] = Field(None, description="Target entity ID")
    details: Optional[str] = Field(None, description="Notes and compliance reasoning")


class AuditLogResponse(BaseModel):
    """Single audit log entry."""
    model_config = ConfigDict(from_attributes=True)

    log_id: str
    timestamp: datetime
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    actor_role: Optional[str] = None
    action_type: str
    target_id: Optional[str] = None
    target_type: Optional[str] = None
    ip_address: Optional[str] = None
    details: Optional[str] = None
    auth_confirmed: bool = True


class AuditLogListResponse(BaseModel):
    """Paginated list of audit entries."""
    logs: List[AuditLogResponse]
    total: int
    page: int
    page_size: int


# ── Streaming & Telemetry schemas ──────────────────────────────────────

class StreamPublishResponse(BaseModel):
    """Asynchronous streaming publish confirmation."""
    status: str = "queued"
    accepted_count: int
    topic: str
    stream_message_ids: List[str]
    ingest_latency_ms: float


class StreamMetricsResponse(BaseModel):
    """Real-time throughput and latency percentiles telemetry."""
    current_ingest_tps: float
    peak_ingest_tps: float
    current_process_tps: float
    peak_process_tps: float
    total_published: int
    total_processed: int
    total_errors: int
    backlog_size: int
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    latency_avg_ms: float
    uptime_seconds: float
    engine_type: str


class BenchmarkRequest(BaseModel):
    """Parameters for running a throughput benchmark load test."""
    transaction_count: int = Field(1000, ge=10, le=50000, description="Total transactions to generate")
    concurrency: int = Field(20, ge=1, le=100, description="Number of concurrent workers")
    mode: str = Field("STREAM", description="STREAM (async) or SYNC (direct)")


class BenchmarkResponse(BaseModel):
    """Benchmark performance results."""
    mode: str
    total_transactions: int
    concurrency: int
    elapsed_seconds: float
    achieved_tps: float
    latency_min_ms: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_p99_ms: float
    latency_max_ms: float
    error_count: int
    status: str



