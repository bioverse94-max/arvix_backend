"""Scoring interface — wraps the ML engines for batch API use.

Provides a clean abstraction over the three ML engines:
  - Pattern-of-Life (PoL): Isolation Forest on behavioral features
  - Graph-Based Detection: Isolation Forest on network/graph features
  - Fusion Engine: XGBoost combining PoL + Graph scores

Currently supports batch scoring only — loads a CSV of transactions,
runs all three engines, and returns scored DataFrames. Single-transaction
real-time scoring requires pre-trained models (future enhancement).
"""
import json
import os
import uuid
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

import pandas as pd
from sqlalchemy.orm import Session

from api.models import Transaction, FraudResult

MODEL_VERSION = "pol_v1+graph_v1+fusion_v1"

# Risk level thresholds (configurable)
RISK_THRESHOLDS = {
    "CRITICAL": 0.80,
    "HIGH": 0.50,
    "MEDIUM": 0.30,
}


@dataclass
class ScoringResult:
    """Result from scoring a single transaction."""
    transaction_id: str
    pol_score: float = 0.0
    graph_score: float = 0.0
    final_risk_score: float = 0.0
    risk_level: str = "LOW"
    risk_flag: bool = False
    fraud_reasons: List[str] = field(default_factory=list)
    model_version: str = MODEL_VERSION
    pol_features: Dict[str, Any] = field(default_factory=dict)
    graph_features: Dict[str, Any] = field(default_factory=dict)


def classify_risk_level(score: float) -> str:
    """Map a 0-1 risk score to a risk level."""
    if score >= RISK_THRESHOLDS["CRITICAL"]:
        return "CRITICAL"
    elif score >= RISK_THRESHOLDS["HIGH"]:
        return "HIGH"
    elif score >= RISK_THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    return "LOW"


def _build_fraud_reasons(row: pd.Series, pol_features: dict, graph_features: dict) -> List[str]:
    """Generate human-readable fraud reasons from feature values."""
    reasons = []
    pol_score = row.get("pol_anomaly_score", 0)
    graph_score = row.get("graph_anomaly_score", 0)

    if pol_score > 0.7:
        reasons.append(f"High Pattern-of-Life anomaly score ({pol_score:.3f})")
    if graph_score > 0.7:
        reasons.append(f"High Graph anomaly score ({graph_score:.3f})")

    # PoL-specific reasons
    if pol_features.get("velocity_60min", 0) > 5:
        reasons.append(f"High transaction velocity ({pol_features['velocity_60min']:.0f} txns/hour)")
    if pol_features.get("pass_through_ratio", 0) > 0.5:
        reasons.append(f"High pass-through ratio ({pol_features['pass_through_ratio']:.2f})")
    if pol_features.get("odd_hour_flag", 0) == 1:
        reasons.append("Transaction at unusual hour for this account")
    if abs(pol_features.get("amount_deviation_zscore", 0)) > 3:
        reasons.append(f"Unusual amount (z-score: {pol_features['amount_deviation_zscore']:.1f})")

    # Graph-specific reasons
    if graph_features.get("cycle_flag", 0) == 1:
        reasons.append("Circular fund flow detected in transaction graph")
    if graph_features.get("in_degree_24h", 0) > 10:
        reasons.append(f"High fan-in: {graph_features['in_degree_24h']:.0f} unique senders in 24h")
    if graph_features.get("new_receiver_ratio_24h", 0) > 0.8:
        reasons.append(f"Sending to mostly new recipients ({graph_features['new_receiver_ratio_24h']:.0%})")

    if not reasons:
        reasons.append("Anomalous pattern detected by ML scoring ensemble")

    return reasons


def _transactions_to_csv(db: Session, transaction_ids: Optional[List[str]] = None) -> str:
    """Export transactions from the DB to a temporary CSV for batch scoring."""
    query = db.query(Transaction)
    if transaction_ids:
        query = query.filter(Transaction.transaction_id.in_(transaction_ids))

    transactions = query.all()
    if not transactions:
        return None

    records = []
    for t in transactions:
        records.append({
            "transaction_id": t.transaction_id,
            "sender_account_id": t.sender_account_id,
            "sender_vpa": f"{t.sender_account_id}@upi",
            "receiver_account_id": t.receiver_account_id,
            "receiver_vpa": f"{t.receiver_account_id}@upi",
            "amount": float(t.amount),
            "timestamp": t.timestamp.isoformat(),
            "status": t.status,
            "currency": "INR",
            "transaction_type": "P2P",
            "channel": "UPI",
            "is_fraud": False,  # Unknown — that's what we're scoring
            "fraud_scenario": None,
        })

    df = pd.DataFrame(records)
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
    df.to_csv(tmp.name, index=False)
    tmp.close()
    return tmp.name


def run_pol_scoring(csv_path: str) -> pd.DataFrame:
    """Run the Pattern-of-Life engine on a CSV and return scored DataFrame."""
    from ml_engines.pattern_of_life.data_prep import load_and_prepare
    from ml_engines.pattern_of_life.baseline import build_account_baselines
    from ml_engines.pattern_of_life.features import build_pol_features
    from ml_engines.pattern_of_life.model import attach_category, score_pattern_of_life

    df, accounts = load_and_prepare(csv_path)
    baseline_df = build_account_baselines(df)
    df = build_pol_features(df, baseline_df)
    df = attach_category(df, baseline_df)
    df = score_pattern_of_life(df)
    return df


def run_graph_scoring(csv_path: str) -> pd.DataFrame:
    """Run the Graph-Based Detection engine on a CSV and return scored DataFrame."""
    from ml_engines.graph_detection.data_prep import load_transactions, prepare_transactions, split_labels
    from ml_engines.graph_detection.features import build_feature_frame
    from ml_engines.graph_detection.model import score_graph_risk

    raw = load_transactions(csv_path)
    cleaned = prepare_transactions(raw)
    feature_ready, labels = split_labels(cleaned)
    feat_df = build_feature_frame(feature_ready)
    scored = score_graph_risk(feat_df)
    return scored


def run_batch_scoring(db: Session, transaction_ids: Optional[List[str]] = None) -> List[ScoringResult]:
    """Run all three ML engines in batch mode on DB transactions.

    Steps:
      1. Export transactions to CSV
      2. Run PoL engine → pol_anomaly_score
      3. Run Graph engine → graph_anomaly_score
      4. Combine scores using a simple weighted fusion (no XGBoost for now,
         since the full fusion engine needs both upstream CSV outputs)
      5. Return ScoringResult objects

    Args:
        db: Active SQLAlchemy session.
        transaction_ids: Optional list of transaction IDs to score. If None, scores all.

    Returns:
        List of ScoringResult objects.
    """
    csv_path = _transactions_to_csv(db, transaction_ids)
    if not csv_path:
        return []

    try:
        # Run PoL
        pol_df = run_pol_scoring(csv_path)

        # Run Graph
        graph_df = run_graph_scoring(csv_path)

        # PoL features to extract per transaction
        pol_feature_cols = [
            "velocity_10min", "velocity_30min", "velocity_60min",
            "sender_diversity_24h", "pass_through_ratio",
            "time_to_forward_min", "odd_hour_flag", "amount_deviation_zscore",
        ]
        # Graph features to extract per transaction
        graph_feature_cols = [
            "in_degree_24h", "out_degree_24h", "new_sender_ratio_24h",
            "new_receiver_ratio_24h", "cycle_flag", "pass_through_ratio",
            "time_to_forward_min",
        ]

        # Build lookup dicts keyed by transaction_id
        pol_lookup = {}
        for _, row in pol_df.iterrows():
            txn_id = row.get("transaction_id")
            if txn_id:
                pol_lookup[txn_id] = {
                    "score": float(row.get("pol_anomaly_score", 0)),
                    "features": {
                        col: float(row.get(col, 0)) for col in pol_feature_cols if col in row.index
                    },
                }

        graph_lookup = {}
        # The graph engine may rename columns
        graph_txn_col = "transaction_id"
        for _, row in graph_df.iterrows():
            txn_id = row.get(graph_txn_col)
            if txn_id:
                graph_lookup[txn_id] = {
                    "score": float(row.get("graph_anomaly_score", 0)),
                    "features": {
                        col: float(row.get(col, 0)) for col in graph_feature_cols if col in row.index
                    },
                }

        # Combine scores: weighted average (configurable)
        POL_WEIGHT = 0.4
        GRAPH_WEIGHT = 0.6
        RISK_THRESHOLD = 0.5

        results = []
        all_txn_ids = set(pol_lookup.keys()) | set(graph_lookup.keys())

        for txn_id in all_txn_ids:
            pol_data = pol_lookup.get(txn_id, {"score": 0.0, "features": {}})
            graph_data = graph_lookup.get(txn_id, {"score": 0.0, "features": {}})

            pol_score = pol_data["score"]
            graph_score = graph_data["score"]

            # Weighted fusion
            final_score = (POL_WEIGHT * pol_score) + (GRAPH_WEIGHT * graph_score)
            # Also consider the max — if either engine flags strongly
            final_score = max(final_score, max(pol_score, graph_score) * 0.85)
            final_score = min(final_score, 1.0)

            risk_level = classify_risk_level(final_score)
            risk_flag = final_score >= RISK_THRESHOLD

            # Build a dummy row for reason generation
            reason_row = pd.Series({
                "pol_anomaly_score": pol_score,
                "graph_anomaly_score": graph_score,
            })
            fraud_reasons = _build_fraud_reasons(reason_row, pol_data["features"], graph_data["features"])

            results.append(ScoringResult(
                transaction_id=txn_id,
                pol_score=pol_score,
                graph_score=graph_score,
                final_risk_score=final_score,
                risk_level=risk_level,
                risk_flag=risk_flag,
                fraud_reasons=fraud_reasons,
                pol_features=pol_data["features"],
                graph_features=graph_data["features"],
            ))

        return results

    finally:
        # Clean up temp file
        try:
            os.unlink(csv_path)
        except OSError:
            pass


def store_scoring_results(results: List[ScoringResult], db: Session) -> int:
    """Persist ScoringResult objects as FraudResult rows.

    Skips transactions that already have a FraudResult.
    Returns the number of new results stored.
    """
    stored = 0
    for r in results:
        existing = db.query(FraudResult).filter(
            FraudResult.transaction_id == r.transaction_id
        ).first()
        if existing:
            continue

        fraud_result = FraudResult(
            result_id=f"FR-{uuid.uuid4().hex[:8]}",
            transaction_id=r.transaction_id,
            pol_score=r.pol_score,
            graph_score=r.graph_score,
            final_risk_score=r.final_risk_score,
            risk_level=r.risk_level,
            risk_flag=r.risk_flag,
            fraud_reasons=json.dumps(r.fraud_reasons),
            model_version=r.model_version,
            pol_features=json.dumps(r.pol_features),
            graph_features=json.dumps(r.graph_features),
        )
        db.add(fraud_result)
        stored += 1

    return stored
