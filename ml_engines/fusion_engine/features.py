"""
features.py — builds the final feature matrix the fusion model trains on.

Three tiers of signal go in:
  1. The 8 raw PoL features (receiver's own-history deviation)
  2. The 10 raw graph features (network-shape deviation)
  3. Three interaction features that only exist BECAUSE we're fusing —
     these are the whole point of this module. A weighted average of two
     scores can't express "both modules agree" vs "the modules disagree
     and one of them might be seeing something the other structurally can't."
"""

import pandas as pd
from .config import (
    POL_SCORE_COL, GRAPH_SCORE_COL,
    POL_FEATURE_COLS, GRAPH_FEATURE_COLS,
    INTERACTION_FEATURES,
)


def build_interaction_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    pol, graph = df[POL_SCORE_COL], df[GRAPH_SCORE_COL]

    # Both modules independently suspicious -> stronger signal than either alone.
    # Multiplicative rather than additive so it stays near-zero unless BOTH fire.
    df["score_product"] = pol * graph

    # "Either one raising a hand is enough to look closer" — this is what
    # directly rescues account_takeover and fan_out, the two scenarios PoL
    # alone scores near-zero on (0.102 and 0.239) but graph is built to catch.
    df["score_max"] = pd.concat([pol, graph], axis=1).max(axis=1)

    # Large disagreement is itself informative: it's the fingerprint of the
    # exact blind-spot pattern documented in Section 17.4/17.3 of the PoL
    # doc — an account whose OWN history looks fine (low PoL) but whose
    # NETWORK POSITION looks like a fresh mule (high graph), or vice versa.
    df["score_disagreement"] = (pol - graph).abs()

    return df


def get_feature_matrix(df: pd.DataFrame):
    """
    Returns (X, feature_names). Keeps this as the single source of truth
    for "what columns does the model actually see" so model.py and any
    SHAP explanation stay in lockstep with the same column order.
    """
    df = build_interaction_features(df)

    feature_cols = (
        POL_FEATURE_COLS
        + GRAPH_FEATURE_COLS
        + [POL_SCORE_COL, GRAPH_SCORE_COL]
        + INTERACTION_FEATURES
    )
    feature_cols = [c for c in feature_cols if c in df.columns]

    X = df[feature_cols].copy()
    return X, feature_cols
