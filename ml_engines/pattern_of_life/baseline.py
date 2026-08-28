import numpy as np
import pandas as pd
from .config import SENDER_COL, RECEIVER_COL, AMOUNT_COL, TIMESTAMP_COL, CATEGORY_COL


def _inbound_view(df):
    return df.rename(columns={RECEIVER_COL: "account_id", SENDER_COL: "counterparty_id"})


def _outbound_view(df):
    return df.rename(columns={SENDER_COL: "account_id", RECEIVER_COL: "counterparty_id"})


def build_account_baselines(df):
    inbound = _inbound_view(df)
    outbound = _outbound_view(df)

    inbound_stats = inbound.groupby("account_id").agg(
        avg_inbound_amount=(AMOUNT_COL, "mean"),
        std_inbound_amount=(AMOUNT_COL, "std"),
        distinct_senders=("counterparty_id", "nunique"),
        inbound_count=(AMOUNT_COL, "count"),
        first_inbound=(TIMESTAMP_COL, "min"),
        last_inbound=(TIMESTAMP_COL, "max"),
    ).reset_index()

    outbound_stats = outbound.groupby("account_id").agg(
        avg_outbound_amount=(AMOUNT_COL, "mean"),
        std_outbound_amount=(AMOUNT_COL, "std"),
        distinct_receivers=("counterparty_id", "nunique"),
        outbound_count=(AMOUNT_COL, "count"),
        first_outbound=(TIMESTAMP_COL, "min"),
        last_outbound=(TIMESTAMP_COL, "max"),
    ).reset_index()

    baseline = pd.merge(inbound_stats, outbound_stats, on="account_id", how="outer")
    baseline = baseline.fillna(0)

    total_days = (
        pd.concat([outbound["timestamp"], inbound["timestamp"]])
        .groupby(pd.concat([outbound["account_id"], inbound["account_id"]]))
        .agg(lambda x: max((x.max() - x.min()).days, 1))
    )
    total_days = total_days.rename("active_days").reset_index()
    total_days.columns = ["account_id", "active_days"]

    baseline = pd.merge(baseline, total_days, on="account_id", how="left")
    baseline["active_days"] = baseline["active_days"].replace(0, 1).fillna(1)

    baseline["avg_inbound_per_day"] = baseline["inbound_count"] / baseline["active_days"]
    baseline["avg_outbound_per_day"] = baseline["outbound_count"] / baseline["active_days"]
    baseline["inbound_outbound_ratio"] = np.where(
        baseline["outbound_count"] > 0,
        baseline["inbound_count"] / baseline["outbound_count"],
        baseline["inbound_count"],
    )

    hours = pd.concat([
        outbound[["account_id", "timestamp"]],
        inbound[["account_id", "timestamp"]],
    ])
    hours["hour"] = hours["timestamp"].dt.hour
    active_hour_sets = hours.groupby("account_id")["hour"].apply(lambda x: set(x.unique()))
    active_hour_sets = active_hour_sets.rename("active_hours").reset_index()

    baseline = pd.merge(baseline, active_hour_sets, on="account_id", how="left")

    categories = df[[SENDER_COL, CATEGORY_COL]].rename(columns={SENDER_COL: "account_id"})
    categories = categories.drop_duplicates(subset=["account_id"])
    baseline = pd.merge(baseline, categories, on="account_id", how="left")
    baseline[CATEGORY_COL] = baseline[CATEGORY_COL].fillna("unclustered")

    return baseline.set_index("account_id")
