"""
data_prep.py — Graph-Based Detection Module

Loads and cleans the transaction stream before any graph is built.
Deliberately mirrors Pattern_of_life/data_prep.py so the two modules stay
consistent (same rows go into both models):

  1. Account-ID fallback: sender_account_id / receiver_account_id are not
     guaranteed by the schema — only the VPAs are. Missing account IDs are
     filled with the corresponding VPA before any graph node is created.
  2. Status filtering: only SUCCESS transactions actually moved money, so
     only those become edges in the graph. (A burst of FAILED attempts to
     unfamiliar recipients is a plausible fraud signal in its own right —
     noted as a v2 extension, not something this prototype claims to catch,
     same scoping call as the PoL module.)
  3. Leakage prevention: fraud_scenario (and is_fraud) are set aside and
     never passed into feature/graph construction — they are reattached
     only at evaluation time.
"""

import pandas as pd

from .config import (
    COL_TIMESTAMP,
    COL_SENDER_VPA,
    COL_SENDER_ACCOUNT_ID,
    COL_RECEIVER_VPA,
    COL_RECEIVER_ACCOUNT_ID,
    COL_STATUS,
    VALID_STATUS,
    COL_FRAUD_SCENARIO,
    COL_IS_FRAUD,
)


def load_transactions(path: str) -> pd.DataFrame:
    """Load the raw transaction CSV."""
    df = pd.read_csv(path)
    return df


def _fallback_account_id(df: pd.DataFrame, account_col: str, vpa_col: str) -> pd.Series:
    """Fill missing account IDs with the corresponding VPA."""
    if account_col not in df.columns:
        return df[vpa_col].astype(str)
    return df[account_col].fillna(df[vpa_col]).astype(str)


def prepare_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean the raw frame into the form the graph builder expects.
    Returns a NEW dataframe — does not mutate the input.
    """
    out = df.copy()

    # --- parse timestamp ---
    out[COL_TIMESTAMP] = pd.to_datetime(out[COL_TIMESTAMP], errors="coerce")
    out = out.dropna(subset=[COL_TIMESTAMP])

    # --- account-ID fallback (fix #1 from PoL Section 14) ---
    out["sender_id_resolved"] = _fallback_account_id(
        out, COL_SENDER_ACCOUNT_ID, COL_SENDER_VPA
    )
    out["receiver_id_resolved"] = _fallback_account_id(
        out, COL_RECEIVER_ACCOUNT_ID, COL_RECEIVER_VPA
    )

    # --- status filtering (fix #2): only money that actually moved ---
    if COL_STATUS in out.columns:
        out = out[out[COL_STATUS] == VALID_STATUS].copy()

    # --- sort chronologically: graph/feature logic assumes time order ---
    out = out.sort_values(COL_TIMESTAMP).reset_index(drop=True)

    return out


def split_labels(df: pd.DataFrame):
    """
    Separate the label columns out for POST-HOC EVALUATION ONLY.
    Mirrors PoL Section 14, fix #3 — fraud_scenario / is_fraud must never
    reach graph construction or feature engineering.
    """
    label_cols = [c for c in (COL_IS_FRAUD, COL_FRAUD_SCENARIO) if c in df.columns]
    labels = df[label_cols].copy() if label_cols else pd.DataFrame(index=df.index)
    features_df = df.drop(columns=label_cols, errors="ignore")
    return features_df, labels
