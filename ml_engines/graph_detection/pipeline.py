"""
pipeline.py — Graph-Based Detection Module

Orchestrates the full flow end to end, mirroring Pattern_of_life/pipeline.py:

load -> clean -> split labels -> build graph features -> score -> reattach
labels for evaluation only -> print results -> write output CSV.
"""

import time

import pandas as pd

from .data_prep import load_transactions, prepare_transactions, split_labels
from .features import build_feature_frame
from .model import score_graph_risk, evaluate_threshold, mean_score_by_scenario
from .config import COL_IS_FRAUD, COL_FRAUD_SCENARIO


def run_pipeline(input_path: str, output_path: str):
    t0 = time.time()

    raw = load_transactions(input_path)
    cleaned = prepare_transactions(raw)
    feature_ready, labels = split_labels(cleaned)

    feat_df = build_feature_frame(feature_ready)
    scored = score_graph_risk(feat_df)

    # reattach labels AFTER scoring — evaluation only, never seen by the model
    scored = scored.reset_index(drop=True)
    labels = labels.reset_index(drop=True)
    for col in (COL_IS_FRAUD, COL_FRAUD_SCENARIO):
        if col in labels.columns:
            scored[col] = labels[col]

    elapsed = time.time() - t0

    scored.to_csv(output_path, index=False)

    print(f"\nProcessed {len(scored):,} transactions in {elapsed:.1f}s")
    print(f"Output written to: {output_path}\n")

    if COL_IS_FRAUD in scored.columns:
        result = evaluate_threshold(scored)
        if result:
            print("Overall threshold evaluation (auto-selected to target >=80% precision):")
            print(f"  threshold: {result['threshold']:.3f}")
            print(f"  precision: {result['precision']:.2f}")
            print(f"  recall:    {result['recall']:.2f}\n")
        else:
            print("No threshold met the target precision bar on this dataset.\n")

        scenario_result = mean_score_by_scenario(scored)
        if scenario_result:
            means, non_fraud_mean = scenario_result
            print("Mean graph_anomaly_score by fraud scenario (higher = more strongly flagged):")
            for scenario, val in means.items():
                print(f"  {scenario:<20s} {val:.3f}")
            print(f"  {'(non-fraud baseline)':<20s} {non_fraud_mean:.3f}\n")

        print("Top 20 highest-risk transactions:")
        top20 = scored.sort_values("graph_anomaly_score", ascending=False).head(20)
        cols = ["transaction_id", "sender_id_resolved", "receiver_id_resolved",
                "amount", "graph_anomaly_score", COL_FRAUD_SCENARIO]
        cols = [c for c in cols if c in top20.columns]
        with pd.option_context("display.max_columns", None, "display.width", 160):
            print(top20[cols].to_string(index=False))

    return scored
