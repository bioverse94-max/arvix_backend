import pandas as pd
from .config import (
    TXN_ID_COL, SENDER_COL, RECEIVER_COL, SENDER_VPA_COL, RECEIVER_VPA_COL,
    AMOUNT_COL, TIMESTAMP_COL, STATUS_COL, VALID_STATUS_VALUES,
    CATEGORY_COL, DEFAULT_CATEGORY, LEAKAGE_COLS,
)


def load_transactions(path):
    df = pd.read_csv(path)
    return df


def resolve_account_identifiers(df):
    if SENDER_COL not in df.columns:
        df[SENDER_COL] = pd.NA
    if RECEIVER_COL not in df.columns:
        df[RECEIVER_COL] = pd.NA
    df[SENDER_COL] = df[SENDER_COL].fillna(df[SENDER_VPA_COL])
    df[RECEIVER_COL] = df[RECEIVER_COL].fillna(df[RECEIVER_VPA_COL])
    return df


def filter_valid_status(df):
    if STATUS_COL in df.columns:
        df = df[df[STATUS_COL].isin(VALID_STATUS_VALUES)]
    return df


def drop_leakage_columns(df):
    cols_to_drop = [c for c in LEAKAGE_COLS if c in df.columns and c != "is_fraud"]
    return df.drop(columns=cols_to_drop, errors="ignore")


def clean_transactions(df):
    df = resolve_account_identifiers(df)
    df = filter_valid_status(df)
    df = drop_leakage_columns(df)
    df = df.dropna(subset=[SENDER_COL, RECEIVER_COL, AMOUNT_COL, TIMESTAMP_COL])
    df = df.drop_duplicates(subset=[TXN_ID_COL])
    df[TIMESTAMP_COL] = pd.to_datetime(df[TIMESTAMP_COL], errors="coerce")
    df = df.dropna(subset=[TIMESTAMP_COL])
    df[AMOUNT_COL] = pd.to_numeric(df[AMOUNT_COL], errors="coerce")
    df = df.dropna(subset=[AMOUNT_COL])
    df = df[df[AMOUNT_COL] > 0]
    df = df.sort_values(TIMESTAMP_COL).reset_index(drop=True)
    return df


def ensure_category_column(df):
    if CATEGORY_COL not in df.columns:
        df[CATEGORY_COL] = DEFAULT_CATEGORY
    else:
        df[CATEGORY_COL] = df[CATEGORY_COL].fillna(DEFAULT_CATEGORY)
    return df


def build_account_table(df):
    senders = df[[SENDER_COL, TIMESTAMP_COL]].rename(columns={SENDER_COL: "account_id"})
    receivers = df[[RECEIVER_COL, TIMESTAMP_COL]].rename(columns={RECEIVER_COL: "account_id"})
    combined = pd.concat([senders, receivers], ignore_index=True)
    accounts = combined.groupby("account_id")[TIMESTAMP_COL].agg(["min", "max", "count"]).reset_index()
    accounts.columns = ["account_id", "first_seen", "last_seen", "activity_count"]
    return accounts


def load_and_prepare(path):
    df = load_transactions(path)
    df = clean_transactions(df)
    df = ensure_category_column(df)
    accounts = build_account_table(df)
    return df, accounts
