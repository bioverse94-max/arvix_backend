"""
model.py — Graph-Based Detection Module

Same modeling philosophy as Pattern_of_life/model.py, for the same reasons
(Section 11/15 of the full context doc):

  - UNSUPERVISED: Isolation Forest never sees the 892 fraud labels during
    fitting. It only learns what a "normal-looking" set of graph features
    looks like, then flags whatever sits far from that.
  - contamination='auto': never derived from the dataset's own fraud ratio.
    Doing so would be leakage-by-proxy and would collapse precision the
    moment this is pointed at real transaction volume (real-world fraud
    is ~0.001-0.002% of transactions, not the ~4.3% in this labeled set).
  - Labels are used ONLY after scoring, to evaluate precision/recall and
    pick a threshold — never to shape the model.
  - Cold-start: accounts with too little graph history (fewer historical
    edges than MIN_HISTORY_EDGES) get a default score rather than an
    unreliable guess — same conservative choice as the PoL module
    (Section 17.1).
"""

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .config import (
    ISOLATION_FOREST_PARAMS,
    MIN_HISTORY_EDGES,
    COLD_START_SCORE,
    TARGET_PRECISION,
    DEFAULT_CATEGORY,
)
from .features import FEATURE_COLUMNS


def _is_cold_start(row) -> bool:
    """
    A transaction is only cold-start if NEITHER party has enough graph
    history to be informative. Checking the receiver alone would wrongly
    mask sender-side anomalies (fan_out, account_takeover) where a
    long-lived, well-connected sender suddenly pays a brand-new,
    one-time receiver — the receiver looks "cold" but the sender's own
    graph position is exactly what should get flagged.
    """
    receiver_history = row.get("receiver_graph_in_degree", 0) + row.get("receiver_graph_out_degree", 0)
    sender_history = row.get("sender_graph_in_degree", 0) + row.get("sender_graph_out_degree", 0)
    return receiver_history < MIN_HISTORY_EDGES and sender_history < MIN_HISTORY_EDGES


def score_graph_risk(feat_df: pd.DataFrame) -> pd.DataFrame:
    """
    Fits one Isolation Forest over the single 'unclustered' bucket (same
    known gap as PoL Section 12 — no declared account-category field
    exists in the schema, so this cannot yet be split into per-category
    models). Returns feat_df with `graph_anomaly_score` (0-1, higher =
    more anomalous) and `account_category` appended.
    """
    out = feat_df.copy()
    out["account_category"] = DEFAULT_CATEGORY

    cold_mask = out.apply(_is_cold_start, axis=1)

    X = out.loc[~cold_mask, FEATURE_COLUMNS].values
    scores = np.full(len(out), COLD_START_SCORE, dtype=float)

    if len(X) > 0:
        model = IsolationForest(**ISOLATION_FOREST_PARAMS)
        model.fit(X)
        raw = -model.score_samples(X)  # higher = more anomalous
        # normalize to 0-1 for interpretability, consistent with the PoL module
        norm = (raw - raw.min()) / (raw.max() - raw.min() + 1e-9)
        scores[~cold_mask.values] = norm

    out["graph_anomaly_score"] = scores
    return out


def evaluate_threshold(df: pd.DataFrame, score_col="graph_anomaly_score",
                        label_col="is_fraud", target_precision=TARGET_PRECISION):
    """
    Sweep candidate thresholds, return the lowest one that meets
    target_precision (same evaluation discipline as the PoL module,
    Section 15/16). Labels are used here ONLY, never during fitting.
    """
    if label_col not in df.columns:
        return None

    candidates = np.unique(np.round(df[score_col].values, 3))
    candidates = np.sort(candidates)[::-1]

    best = None
    for t in candidates:
        flagged = df[score_col] >= t
        n_flagged = flagged.sum()
        if n_flagged == 0:
            continue
        tp = (flagged & df[label_col]).sum()
        precision = tp / n_flagged
        recall = tp / df[label_col].sum() if df[label_col].sum() else 0.0
        if precision >= target_precision:
            best = {"threshold": float(t), "precision": float(precision), "recall": float(recall)}
        else:
            if best is not None:
                break
    return best


def mean_score_by_scenario(df: pd.DataFrame, score_col="graph_anomaly_score",
                            scenario_col="fraud_scenario", fraud_col="is_fraud"):
    if scenario_col not in df.columns:
        return None
    fraud_rows = df[df[fraud_col]]
    means = fraud_rows.groupby(scenario_col)[score_col].mean().sort_values(ascending=False)
    non_fraud_mean = df[~df[fraud_col]][score_col].mean()
    return means, non_fraud_mean
