"""Generator service — bridges generators/ & scenarios/ to DB & ML Scoring.

Generates synthetic UPI environments, normal transactions, and injected fraud scenarios,
ingests them into SQLite/PostgreSQL, runs ML batch scoring (PoL + Graph engines),
creates FraudResult and Alert database entities, and returns the dataset.
"""
import uuid
import json
from datetime import datetime, timezone
from typing import List, Dict, Any

from sqlalchemy.orm import Session

from config.config import Config
from utils.random_utils import RandomProvider
from generators.environment_generator import EnvironmentGenerator
from generators.transaction_generator import TransactionGenerator
from scenarios.account_takeover import AccountTakeoverScenario
from scenarios.circular_flow import CircularFlowScenario
from scenarios.fan_in import FanInScenario
from scenarios.fan_out import FanOutScenario
from scenarios.mule_network import MuleNetworkScenario
from scenarios.rapid_pass_through import RapidPassThroughScenario

from api.models import Account, Transaction, FraudResult, Alert
from api import scoring_interface, alert_service, audit_service

SCENARIO_REGISTRY = {
    "account_takeover": AccountTakeoverScenario,
    "mule_network": MuleNetworkScenario,
    "fan_in": FanInScenario,
    "fan_out": FanOutScenario,
    "rapid_pass_through": RapidPassThroughScenario,
    "circular_flow": CircularFlowScenario,
}


def _chunked_in_query(db: Session, model_attr, id_list: List[str], chunk_size: int = 500) -> set:
    """Helper to query in batches to avoid SQLite variable limit on large datasets."""
    existing = set()
    for i in range(0, len(id_list), chunk_size):
        chunk = id_list[i : i + chunk_size]
        rows = db.query(model_attr).filter(model_attr.in_(chunk)).all()
        for r in rows:
            existing.add(r[0])
    return existing


def _ensure_accounts(db: Session, account_ids: List[str]):
    """Ensure account records exist in DB so FK constraints pass."""
    unique_ids = list(set(account_ids))
    existing_ids = _chunked_in_query(db, Account.account_id, unique_ids)
    
    new_accounts = []
    for acc_id in unique_ids:
        if acc_id not in existing_ids:
            vpa = f"{acc_id.lower()}@upi" if "@" not in acc_id else acc_id
            new_accounts.append(Account(
                account_id=acc_id,
                vpa=vpa,
                kyc_tier="VERIFIED",
                account_age_days=180,
                current_risk_tier="LOW",
                is_stub=True
            ))
    if new_accounts:
        for i in range(0, len(new_accounts), 1000):
            db.bulk_save_objects(new_accounts[i : i + 1000])
        db.commit()


def run_synthetic_generator(
    db: Session,
    num_accounts: int = 100,
    num_normal_transactions: int = 200,
    scenarios: List[str] = None,
    seed: int = 42,
    reset_db: bool = False,
) -> Dict[str, Any]:
    """Runs the synthetic UPI generator, saves records to DB, runs ML predictions,
    and returns generation statistics along with scored transactions."""

    if reset_db:
        db.query(Alert).delete()
        db.query(FraudResult).delete()
        db.query(Transaction).delete()
        db.commit()

    if scenarios is None:
        scenarios = ["mule_network", "account_takeover", "circular_flow"]

    class RunConfig(Config):
        NUM_ACCOUNTS = max(10, num_accounts)
        NUM_MERCHANTS = max(5, int(num_accounts * 0.2))
        NUM_NORMAL_TRANSACTIONS = max(10, num_normal_transactions)

    rng = RandomProvider(seed=seed)
    env = EnvironmentGenerator(rng, RunConfig).build()
    raw_txns = TransactionGenerator(rng, RunConfig).generate_normal(env, RunConfig.NUM_NORMAL_TRANSACTIONS)

    # Inject selected scenarios
    for scenario_name in scenarios:
        scenario_cls = SCENARIO_REGISTRY.get(scenario_name)
        if scenario_cls:
            scenario_txns = scenario_cls(rng, RunConfig).generate(env, num_incidents=2)
            raw_txns.extend(scenario_txns)

    rng.shuffle(raw_txns)

    # Collect all unique account IDs for DB FK setup
    all_account_ids = []
    for t in raw_txns:
        all_account_ids.append(t["sender_account_id"])
        all_account_ids.append(t["receiver_account_id"])

    _ensure_accounts(db, all_account_ids)

    # Bulk insert transactions into DB (skipping duplicates)
    all_txn_ids = [t["transaction_id"] for t in raw_txns]
    existing_txn_ids = _chunked_in_query(db, Transaction.transaction_id, all_txn_ids)

    db_txns = []
    for t in raw_txns:
        if t["transaction_id"] in existing_txn_ids:
            continue

        ts = t["timestamp"]
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.now(timezone.utc)
        else:
            dt = ts

        db_txns.append(
            Transaction(
                transaction_id=t["transaction_id"],
                sender_account_id=t["sender_account_id"],
                receiver_account_id=t["receiver_account_id"],
                amount=float(t["amount"]),
                timestamp=dt,
                status=t.get("status", "SUCCESS"),
            )
        )

    if db_txns:
        for i in range(0, len(db_txns), 1000):
            db.bulk_save_objects(db_txns[i : i + 1000])
        db.commit()

    # Trigger ML Batch Scoring Engine
    new_txn_ids = [t.transaction_id for t in db_txns]
    scoring_results = scoring_interface.run_batch_scoring(db, new_txn_ids)
    stored_scores = scoring_interface.store_scoring_results(scoring_results, db)
    db.commit()

    # Generate Alerts for scored transactions with high risk or fraud flag
    scored_map = {r.transaction_id: r for r in scoring_results}
    existing_alert_ids = _chunked_in_query(db, Alert.transaction_id, all_txn_ids)
    
    new_alerts = []
    for t_dict in raw_txns:
        t_id = t_dict["transaction_id"]
        res = scored_map.get(t_id)
        is_fraud = t_dict.get("is_fraud", False) or (res and res.risk_flag)

        if is_fraud or (res and res.risk_level in ["HIGH", "CRITICAL"]):
            if t_id not in existing_alert_ids:
                risk_score_val = res.final_risk_score * 100 if res else (92.0 if is_fraud else 65.0)
                severity_val = res.risk_level if res else ("CRITICAL" if is_fraud else "HIGH")
                title_text = f"Fraud Scenario Detected: {t_dict.get('fraud_scenario') or 'Suspicious Pattern'}"
                
                new_alerts.append(
                    Alert(
                        alert_id=f"ALT_{uuid.uuid4().hex[:8].upper()}",
                        transaction_id=t_id,
                        alert_type="FRAUD_DETECTED" if is_fraud else "SUSPICIOUS_PATTERN",
                        severity=severity_val,
                        status="OPEN",
                        title=title_text,
                        description=", ".join(res.fraud_reasons) if res and res.fraud_reasons else "Flagged by Synthetic UPI Generator",
                        fraud_scenario=t_dict.get("fraud_scenario"),
                        risk_score=risk_score_val,
                    )
                )

    if new_alerts:
        for i in range(0, len(new_alerts), 1000):
            db.bulk_save_objects(new_alerts[i : i + 1000])
        db.commit()

    audit_service.record_audit_log(
        db=db,
        action_type="GENERATE_SYNTHETIC_DATASET",
        target_type="SYSTEM",
        details=f"Generated {len(raw_txns)} synthetic transactions ({len(new_alerts)} alerts, {stored_scores} ML scores).",
    )

    return {
        "status": "success",
        "generated_transactions": len(raw_txns),
        "inserted_transactions": len(db_txns),
        "ml_scores_computed": len(scoring_results),
        "alerts_created": len(new_alerts),
        "scenarios_injected": scenarios,
    }
