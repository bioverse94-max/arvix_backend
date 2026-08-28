"""
pipeline.py — orchestrates the full fusion flow end to end, mirroring the
structure of the PoL module's own pipeline.py so the two are easy to read
side by side.
"""

import pandas as pd
from .config import (
    KEY_COL, LABEL_COL, SCENARIO_COL,
    POL_INPUT_PATH, GRAPH_INPUT_PATH, OUTPUT_PATH, SHAP_SUMMARY_PATH,
)
from .data_prep import load_and_merge, clean_and_impute
from .features import build_interaction_features, get_feature_matrix
from .model import (
    train_test_split_stratified, fit_model, cross_validate,
    select_threshold, evaluate, shap_importance,
)


def run_pipeline(pol_path=POL_INPUT_PATH, graph_path=GRAPH_INPUT_PATH,
                  output_path=OUTPUT_PATH):
    # 1. Merge the two upstream modules' outputs into one row per transaction
    df = load_and_merge(pol_path, graph_path)
    df = clean_and_impute(df)

    # 2. Build the fusion feature matrix (raw features + both scores + interactions)
    X, feature_names = get_feature_matrix(df)
    y = df[LABEL_COL].astype(int)
    scenario = df[SCENARIO_COL] if SCENARIO_COL in df.columns else pd.Series(["unknown"] * len(df))

    # 3. Stratified train/test split
    X_train, X_test, y_train, y_test, sc_train, sc_test = train_test_split_stratified(X, y, scenario)

    # 4. Train the class-weighted XGBoost fusion model
    model = fit_model(X_train, y_train)

    # 5. Cross-validate on the full dataset as a sanity check against split luck
    cross_validate(model, X, y)

    # 6. Pick an operating threshold on the test set at the target precision bar
    test_scores = model.predict_proba(X_test)[:, 1]
    threshold, achieved_precision, achieved_recall = select_threshold(y_test, test_scores)

    # 7. Full evaluation report, including per-scenario recall
    metrics = evaluate(model, X_test, y_test, sc_test, threshold)

    # 8. SHAP global + per-transaction explainability
    importance, shap_values = shap_importance(model, X_test, feature_names, SHAP_SUMMARY_PATH)

    # 9. Score EVERY transaction (train + test) for the final output file —
    #    the deployed model scores the whole population, not just the holdout.
    df["final_risk_score"] = model.predict_proba(X)[:, 1]
    df["final_risk_flag"] = (df["final_risk_score"] >= threshold).astype(int)

    out_cols = [KEY_COL, LABEL_COL, SCENARIO_COL] + [
        c for c in df.columns
        if c not in (KEY_COL, LABEL_COL, SCENARIO_COL, "final_risk_score", "final_risk_flag")
    ] + ["final_risk_score", "final_risk_flag"]
    out_cols = [c for c in out_cols if c in df.columns]

    df[out_cols].to_csv(output_path, index=False)
    print(f"\n[pipeline] Wrote {len(df)} scored transactions to {output_path}")
    print(f"[pipeline] Operating threshold: {threshold:.3f} "
          f"(precision={achieved_precision:.3f}, recall={achieved_recall:.3f})")

    return model, df, metrics, importance
