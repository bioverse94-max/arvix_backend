import numpy as np
import pandas as pd
from .config import (
    SENDER_COL, RECEIVER_COL, AMOUNT_COL, TIMESTAMP_COL,
    VELOCITY_WINDOWS_MIN, PASS_THROUGH_WINDOW_MIN,
)


def _velocity_features(df):
    df = df.sort_values(TIMESTAMP_COL).reset_index(drop=True)
    out = {f"velocity_{w}min": np.zeros(len(df)) for w in VELOCITY_WINDOWS_MIN}
    for account, group in df.groupby(RECEIVER_COL):
        times = group[TIMESTAMP_COL].values
        idx = group.index.values
        for w in VELOCITY_WINDOWS_MIN:
            window = np.timedelta64(w, "m")
            counts = np.zeros(len(times))
            left = 0
            for right in range(len(times)):
                while times[right] - times[left] > window:
                    left += 1
                counts[right] = right - left
            out[f"velocity_{w}min"][idx] = counts
    for w in VELOCITY_WINDOWS_MIN:
        df[f"velocity_{w}min"] = out[f"velocity_{w}min"]
    return df


def _sender_diversity_24h(df):
    df = df.sort_values(TIMESTAMP_COL).reset_index(drop=True)
    result = np.zeros(len(df))
    window = np.timedelta64(24, "h")
    for account, group in df.groupby(RECEIVER_COL):
        times = group[TIMESTAMP_COL].values
        senders = group[SENDER_COL].values
        idx = group.index.values
        left = 0
        seen = {}
        for right in range(len(times)):
            seen[senders[right]] = seen.get(senders[right], 0) + 1
            while times[right] - times[left] > window:
                s = senders[left]
                seen[s] -= 1
                if seen[s] == 0:
                    del seen[s]
                left += 1
            result[idx[right]] = len(seen)
    df["sender_diversity_24h"] = result
    return df


def _pass_through_and_time_to_forward(df):
    df = df.sort_values(TIMESTAMP_COL).reset_index(drop=True)
    ratio = np.zeros(len(df))
    ttf = np.full(len(df), np.nan)
    window = np.timedelta64(PASS_THROUGH_WINDOW_MIN, "m")
    outbound_by_account = {
        account: group.sort_values(TIMESTAMP_COL)
        for account, group in df.groupby(SENDER_COL)
    }
    for i, row in df.iterrows():
        account = row[RECEIVER_COL]
        t0 = row[TIMESTAMP_COL]
        amt_in = row[AMOUNT_COL]
        if account not in outbound_by_account:
            continue
        out_group = outbound_by_account[account]
        mask = (out_group[TIMESTAMP_COL] > t0) & (out_group[TIMESTAMP_COL] <= t0 + window)
        matched = out_group[mask]
        if len(matched) > 0:
            ratio[i] = min(matched[AMOUNT_COL].sum() / amt_in, 1.0)
            first_out = matched[TIMESTAMP_COL].min()
            ttf[i] = (first_out - t0).total_seconds() / 60.0
    df["pass_through_ratio"] = ratio
    df["time_to_forward_min"] = ttf
    return df


def _odd_hour_flag(df, baselines):
    def is_odd(row):
        acc = baselines.get(row[RECEIVER_COL])
        if acc is None:
            return 0
        hours = acc.get("active_hours", set())
        if not hours:
            return 0
        return int(row[TIMESTAMP_COL].hour not in hours)
    df["odd_hour_flag"] = df.apply(is_odd, axis=1)
    return df


def _amount_deviation(df, baselines):
    def zscore(row):
        acc = baselines.get(row[RECEIVER_COL])
        if acc is None:
            return 0.0
        mean = acc.get("avg_inbound_amount", 0.0)
        std = acc.get("std_inbound_amount", 0.0)
        if std == 0:
            return 0.0
        return (row[AMOUNT_COL] - mean) / std
    df["amount_deviation_zscore"] = df.apply(zscore, axis=1)
    return df


def build_pol_features(df, baseline_df):
    baselines = baseline_df.to_dict(orient="index")
    df = _velocity_features(df)
    df = _sender_diversity_24h(df)
    df = _pass_through_and_time_to_forward(df)
    df = _odd_hour_flag(df, baselines)
    df = _amount_deviation(df, baselines)
    df["time_to_forward_min"] = df["time_to_forward_min"].fillna(df["time_to_forward_min"].max())
    return df
