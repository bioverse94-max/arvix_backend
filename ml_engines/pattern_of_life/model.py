import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import precision_recall_curve
from .config import (
    RECEIVER_COL, LABEL_COL, ISO_FOREST_CONTAMINATION, ISO_FOREST_N_ESTIMATORS,
    ISO_FOREST_RANDOM_STATE, DEFAULT_CATEGORY,
)

FEATURE_COLUMNS = [
    "velocity_10min", "velocity_30min", "velocity_60min",
    "sender_diversity_24h", "pass_through_ratio",
    "time_to_forward_min", "odd_hour_flag", "amount_deviation_zscore",
]


def attach_category(df, baseline_df):
    cat_map = baseline_df["account_category"].to_dict()
    df["account_category"] = df[RECEIVER_COL].map(cat_map).fillna(DEFAULT_CATEGORY)
    return df


def score_pattern_of_life(df, min_rows_for_model=30):
    df = df.copy()
    df["pol_anomaly_score"] = 0.0
    scaler = MinMaxScaler()

    for category, group in df.groupby("account_category"):
        X = group[FEATURE_COLUMNS].fillna(0).values
        if len(group) < min_rows_for_model:
            df.loc[group.index, "pol_anomaly_score"] = 0.0
            continue
        model = IsolationForest(
            n_estimators=ISO_FOREST_N_ESTIMATORS,
            contamination=ISO_FOREST_CONTAMINATION,
            random_state=ISO_FOREST_RANDOM_STATE,
        )
        model.fit(X)
        raw_scores = -model.score_samples(X)
        scaled = scaler.fit_transform(raw_scores.reshape(-1, 1)).flatten()
        df.loc[group.index, "pol_anomaly_score"] = scaled

    return df


def evaluate_threshold(df, target_precision=0.8):
    if LABEL_COL not in df.columns:
        return None
    y_true = df[LABEL_COL].astype(int).values
    y_score = df["pol_anomaly_score"].values
    precision, recall, thresholds = precision_recall_curve(y_true, y_score)
    valid = precision[:-1] >= target_precision
    if not valid.any():
        best_idx = int(np.argmax(precision[:-1]))
    else:
        best_idx = int(np.argmax(recall[:-1] * valid))
    return {
        "threshold": float(thresholds[best_idx]),
        "precision": float(precision[best_idx]),
        "recall": float(recall[best_idx]),
    }
