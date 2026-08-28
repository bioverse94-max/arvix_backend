"""
data_prep.py — loads the two upstream outputs and merges them into one row
per transaction. This is the join point of the whole system: PoL scores a
transaction from the receiver's history, Graph scores it from the network's
shape, and this is where those two independent opinions first meet.

Both real upstream files use different raw column names than the fusion
layer's canonical vocabulary (see GRAPH_RAW_COL_MAP / GRAPH_SCORE_RAW_COL
in config.py) and, in the graph file's case, some raw column names
(pass_through_ratio, time_to_forward_min) are also reused with different
meanings by the pol file. Renaming happens here, immediately after load,
so every other module only ever sees the canonical names.
"""

import pandas as pd
import numpy as np
from .config import (
    KEY_COL, LABEL_COL, SCENARIO_COL,
    POL_SCORE_COL, GRAPH_SCORE_COL, GRAPH_SCORE_RAW_COL,
    POL_FEATURE_COLS, GRAPH_FEATURE_COLS, GRAPH_RAW_COL_MAP,
)


def load_and_merge(pol_path: str, graph_path: str) -> pd.DataFrame:
    """
    Loads both scored CSVs, renames each to the canonical column
    vocabulary, and inner-joins them on transaction_id.

    Inner join is deliberate, not lazy: a transaction that's missing from
    either module's output means one module never got to score it (e.g. it
    was filtered out upstream). Fusing a half-formed opinion would be worse
    than not fusing at all, so those rows are dropped and counted, not
    silently imputed with a guessed score.
    """
    pol_df = pd.read_csv(pol_path)
    graph_df = pd.read_csv(graph_path)

    # --- pol side: raw names already match the canonical POL_FEATURE_COLS
    # and POL_SCORE_COL. The real pol file has no fraud_scenario column —
    # that only exists in the graph file — so it's not selected here.
    pol_only_cols = [KEY_COL, LABEL_COL, POL_SCORE_COL] + POL_FEATURE_COLS
    pol_df = pol_df[[c for c in pol_only_cols if c in pol_df.columns]]

    # --- graph side: rename the real raw columns to canonical names BEFORE
    # selecting, so the same column name used by both files (e.g.
    # pass_through_ratio, time_to_forward_min) never collides during merge.
    graph_df = graph_df.rename(columns={GRAPH_SCORE_RAW_COL: GRAPH_SCORE_COL,
                                         **GRAPH_RAW_COL_MAP})
    graph_only_cols = [KEY_COL, SCENARIO_COL, GRAPH_SCORE_COL] + GRAPH_FEATURE_COLS
    graph_df = graph_df[[c for c in graph_only_cols if c in graph_df.columns]]

    before_pol, before_graph = len(pol_df), len(graph_df)
    merged = pol_df.merge(graph_df, on=KEY_COL, how="inner", validate="one_to_one")
    dropped = (before_pol - len(merged)) + (before_graph - len(merged))

    if dropped > 0:
        print(f"[data_prep] Dropped {dropped} unmatched rows during merge "
              f"(present in one module's output but not the other).")

    print(f"[data_prep] Merged dataset: {len(merged)} transactions, "
          f"{merged[LABEL_COL].sum()} labeled fraud "
          f"({100 * merged[LABEL_COL].mean():.3f}% positive rate).")

    return merged


def clean_and_impute(df: pd.DataFrame) -> pd.DataFrame:
    """
    Light cleaning pass. Both upstream modules already do their own
    cleaning (VPA fallback, status filtering, cold-start defaults) — this
    step only handles what can go wrong specifically at the merge boundary.
    """
    df = df.copy()

    feature_cols = [c for c in df.columns
                     if c not in (KEY_COL, LABEL_COL, SCENARIO_COL)]

    # Any remaining NaNs at this point are cold-start rows from one module
    # that weren't cold-start in the other. Median-impute per column rather
    # than dropping the row — dropping would bias the dataset toward
    # "accounts with rich history in both modules," which skews evaluation.
    n_missing = df[feature_cols].isna().sum().sum()
    if n_missing > 0:
        print(f"[data_prep] Imputing {n_missing} missing feature values with column medians.")
        df[feature_cols] = df[feature_cols].fillna(df[feature_cols].median(numeric_only=True))

    # Guardrail: both anomaly scores are defined on [0, 1]. Clip defensively
    # in case an upstream module's scaler drifted.
    df[POL_SCORE_COL] = df[POL_SCORE_COL].clip(0, 1)
    df[GRAPH_SCORE_COL] = df[GRAPH_SCORE_COL].clip(0, 1)

    return df
