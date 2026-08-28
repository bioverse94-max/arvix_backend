"""
model.py — trains the fusion classifier and turns it into a usable risk score.

Design choice, stated up front: this is SUPERVISED, unlike PoL and Graph
underneath it. That's intentional and fine at this layer specifically —
by the time we're fusing, the two unsupervised modules have already done
the hard job of turning raw transactions into meaningful anomaly signals
without ever seeing a fraud label. The fusion layer's only job is learning
HOW to weigh two already-informative numbers (plus their raw features)
against each other. That's a small, well-posed supervised problem — not
"learn what fraud looks like from scratch," which is what would have made
supervision risky at the PoL/Graph stage (Section 11 of the PoL doc).

We still respect the same imbalance discipline PoL used:
- Stratified split (not random) so the tiny positive class doesn't
  vanish from either train or test set by chance.
- class-weighting via scale_pos_weight, not oversampling — oversampling
  892 rows into a much larger synthetic positive class risks the model
  memorizing the synthetic generator's noise, same concern flagged in
  Section 11 of the PoL doc for a from-scratch supervised classifier.
- Threshold picked to hit a target precision, not accuracy or a fixed 0.5
  cutoff, since accuracy is meaningless at this class ratio (predicting
  "never fraud" scores >95% accuracy and is worthless).
"""

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.metrics import (
    precision_recall_curve, roc_auc_score, average_precision_score,
    precision_score, recall_score, f1_score, classification_report,
)
from xgboost import XGBClassifier

from .config import (
    LABEL_COL, SCENARIO_COL, TEST_SIZE, RANDOM_STATE,
    TARGET_PRECISION, CROSS_VAL_FOLDS, XGB_PARAMS,
)


def train_test_split_stratified(X, y, scenario):
    X_train, X_test, y_train, y_test, sc_train, sc_test = train_test_split(
        X, y, scenario,
        test_size=TEST_SIZE,
        random_state=RANDOM_STATE,
        stratify=y,          # guarantees train/test both keep ~same fraud ratio
    )
    return X_train, X_test, y_train, y_test, sc_train, sc_test


def fit_model(X_train, y_train):
    n_pos = y_train.sum()
    n_neg = len(y_train) - n_pos
    scale_pos_weight = n_neg / max(n_pos, 1)   # class-weighting for the 20:1+ imbalance

    print(f"[model] Training on {len(X_train)} rows "
          f"({n_pos} fraud / {n_neg} normal, scale_pos_weight={scale_pos_weight:.1f})")

    model = XGBClassifier(**XGB_PARAMS, scale_pos_weight=scale_pos_weight)
    model.fit(X_train, y_train)
    return model


def cross_validate(model, X, y):
    """5-fold stratified CV on PR-AUC, to sanity-check the holdout split
    wasn't a lucky/unlucky draw given how few positive rows exist."""
    skf = StratifiedKFold(n_splits=CROSS_VAL_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    scores = cross_val_score(model, X, y, cv=skf, scoring="average_precision")
    print(f"[model] 5-fold CV PR-AUC: {scores.mean():.3f} (+/- {scores.std():.3f})")
    return scores


def select_threshold(y_true, y_scores, target_precision=TARGET_PRECISION):
    """
    Same methodology PoL used (Section 16): pick the lowest threshold that
    still clears the target precision bar, so recall is maximized subject
    to that precision constraint rather than picked arbitrarily.
    """
    precisions, recalls, thresholds = precision_recall_curve(y_true, y_scores)
    # precision_recall_curve returns len(thresholds) = len(precisions) - 1
    valid = np.where(precisions[:-1] >= target_precision)[0]
    if len(valid) == 0:
        # Target precision unreachable at any threshold — fall back to best F1.
        f1s = 2 * precisions[:-1] * recalls[:-1] / (precisions[:-1] + recalls[:-1] + 1e-9)
        best_idx = np.argmax(f1s)
        print(f"[model] WARNING: target precision {target_precision} unreachable — "
              f"falling back to best-F1 threshold instead.")
    else:
        best_idx = valid[0]   # lowest threshold that clears the bar -> highest recall at that precision

    return thresholds[best_idx], precisions[best_idx], recalls[best_idx]


def evaluate(model, X_test, y_test, scenario_test, threshold):
    y_scores = model.predict_proba(X_test)[:, 1]
    y_pred = (y_scores >= threshold).astype(int)

    roc_auc = roc_auc_score(y_test, y_scores)
    pr_auc = average_precision_score(y_test, y_scores)
    precision = precision_score(y_test, y_pred, zero_division=0)
    recall = recall_score(y_test, y_pred, zero_division=0)
    f1 = f1_score(y_test, y_pred, zero_division=0)

    print("\n[model] === Held-out test set performance ===")
    print(f"  threshold        : {threshold:.3f}")
    print(f"  precision        : {precision:.3f}")
    print(f"  recall           : {recall:.3f}")
    print(f"  f1               : {f1:.3f}")
    print(f"  ROC-AUC          : {roc_auc:.3f}")
    print(f"  PR-AUC           : {pr_auc:.3f}")

    # Per-scenario recall — the metric that actually matters for the pitch:
    # did fusion close the account_takeover / fan_out gap PoL alone had?
    print("\n[model] Recall by fraud scenario (test set):")
    results = pd.DataFrame({
        "y_true": y_test.values, "y_pred": y_pred, "scenario": scenario_test.values,
    })
    fraud_rows = results[results["y_true"] == 1]
    scenario_recall = fraud_rows.groupby("scenario")["y_pred"].mean().sort_values(ascending=False)
    for scen, rec in scenario_recall.items():
        n = (fraud_rows["scenario"] == scen).sum()
        print(f"    {scen:<20s} recall={rec:.3f}  (n={n})")

    return {
        "roc_auc": roc_auc, "pr_auc": pr_auc,
        "precision": precision, "recall": recall, "f1": f1,
        "scenario_recall": scenario_recall,
    }


def shap_importance(model, X_sample, feature_names, out_path):
    """
    Global feature importance via SHAP, per the fusion plan in Section 19
    of the PoL doc ("SHAP for per-flag explainability"). This answers the
    judge question "why did the fusion model flag this transaction?" at
    both the global level (this function) and, via the same shap_values,
    the per-transaction level (one row of shap_values = one explanation).
    """
    import shap
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_sample)

    mean_abs_shap = np.abs(shap_values).mean(axis=0)
    importance = pd.DataFrame({
        "feature": feature_names,
        "mean_abs_shap": mean_abs_shap,
    }).sort_values("mean_abs_shap", ascending=False)

    importance.to_csv(out_path, index=False)
    print(f"\n[model] Top 8 features by mean |SHAP value|:")
    for _, row in importance.head(8).iterrows():
        print(f"    {row['feature']:<25s} {row['mean_abs_shap']:.4f}")

    return importance, shap_values
