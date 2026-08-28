"""
config.py — all tunable constants for the Fusion Layer in one place.
Nothing in the other files should hardcode a threshold, column name,
or hyperparameter — it should all trace back here.
"""

# ---------------------------------------------------------------------------
# Canonical column names used EVERYWHERE downstream of data_prep.py
# (features.py, model.py, pipeline.py). data_prep.py is the only place
# that knows about the real, raw upstream CSV column names below — once
# load_and_merge() has run, the rest of the codebase only ever sees these.
# ---------------------------------------------------------------------------
KEY_COL = "transaction_id"
LABEL_COL = "is_fraud"
SCENARIO_COL = "fraud_scenario"          # dropped before training — leakage risk

POL_SCORE_COL = "pol_anomaly_score"
GRAPH_SCORE_COL = "graph_risk_score"

# The 8 Pattern-of-Life features (from SIH_Pattern_of_Life_Implementation2.md, Section 13)
POL_FEATURE_COLS = [
    "velocity_10min",
    "velocity_30min",
    "velocity_60min",
    "sender_diversity_24h",
    "pass_through_ratio",
    "time_to_forward_min",
    "odd_hour_flag",
    "amount_deviation_zscore",
]

# The graph-structure features (from Graph_Based_Detection_Explainer3.md, Section 3)
# — canonical/internal names. See GRAPH_RAW_COL_MAP below for what these are
# actually called in graph_scored_transactions.csv.
GRAPH_FEATURE_COLS = [
    "fan_in_24h",                 # 3A — strangers paying in
    "fan_out_1h",                 # 3A — sudden new outbound spray
    "new_receiver_ratio",         # 3A — paying people never paid before
    "loop_closed_flag",           # 3A — circular flow A->B->C->A
    "graph_pass_through_ratio",   # 3B — money in that leaves again fast
    "cash_out_speed_min",         # 3B — how fast it left
    "destination_repeat_ratio",   # 3C — same suppliers vs new strangers
    "bidirectional_flow_ratio",   # 3C — two-way relationship vs one-way pipe
    "funnel_collapse_ratio",      # 3C — many-in -> few-out shape
    "dead_end_score",             # 3C — terminal "last mile" cash-out candidate
]

# ---------------------------------------------------------------------------
# RAW -> CANONICAL name mapping for the real upstream files.
#
# The actual pol_scored_transactions.csv / graph_scored_transactions.csv
# produced by your two upstream modules use different column names than
# the ones the fusion layer was originally written against. data_prep.py
# renames columns through these maps immediately after loading, so nothing
# past that point ever has to know the raw names existed.
# ---------------------------------------------------------------------------

# pol_scored_transactions.csv: the 8 raw PoL feature names already match
# POL_FEATURE_COLS exactly, and its score column is already "pol_anomaly_score".
# NOTE: the real pol file has no fraud_scenario column at all — only the
# graph file does — so SCENARIO_COL is pulled from the graph side instead.
POL_RAW_COL_MAP = {}   # no renaming needed on the pol side

# graph_scored_transactions.csv: real column -> canonical name.
# graph_anomaly_score is the real score column (config used to call it
# graph_risk_score, which doesn't exist in the file — that was the bug).
GRAPH_SCORE_RAW_COL = "graph_anomaly_score"

# Real graph raw feature columns are named around degree/graph terminology
# rather than the fan_in/fan_out vocabulary GRAPH_FEATURE_COLS uses. Two
# approximations worth knowing about:
#   - fan_out_1h is mapped from out_degree_24h (no 1h-window column exists
#     upstream; this is the closest available signal).
#   - cash_out_speed_min is mapped from the graph file's own
#     time_to_forward_min (a separate, graph-computed column — distinct
#     from PoL's own time_to_forward_min of the same name, which is why
#     both files having a same-named column was silently colliding on merge).
GRAPH_RAW_COL_MAP = {
    "in_degree_24h": "fan_in_24h",
    "out_degree_24h": "fan_out_1h",
    "new_receiver_ratio_24h": "new_receiver_ratio",
    "cycle_flag": "loop_closed_flag",
    "pass_through_ratio": "graph_pass_through_ratio",
    "time_to_forward_min": "cash_out_speed_min",
    "receiver_repeat_destination_ratio": "destination_repeat_ratio",
    "receiver_reciprocity_ratio": "bidirectional_flow_ratio",
    "receiver_downstream_funnel_concentration": "funnel_collapse_ratio",
    "receiver_last_mile_candidate": "dead_end_score",
}

# ---------------------------------------------------------------------------
# Fusion feature set = both raw feature families + both scores + interactions
# ---------------------------------------------------------------------------
INTERACTION_FEATURES = [
    "score_product",     # pol_score * graph_score — both modules agreeing, amplified
    "score_max",         # max(pol_score, graph_score) — "either one is enough to worry"
    "score_disagreement", # |pol_score - graph_score| — one module sees it, other doesn't
]

# ---------------------------------------------------------------------------
# Train / evaluation settings
# ---------------------------------------------------------------------------
TEST_SIZE = 0.30
RANDOM_STATE = 42
TARGET_PRECISION = 0.95        # fusion clears the 0.80 bar PoL alone was held to with
                                # huge margin, so the bar is raised here for a harder,
                                # more realistic deployment target
CROSS_VAL_FOLDS = 5

# XGBoost hyperparameters — deliberately shallow/conservative given only ~900
# positive rows total; a deep model would just memorize the synthetic generator.
XGB_PARAMS = {
    "n_estimators": 300,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "reg_lambda": 1.5,
    "eval_metric": "aucpr",       # PR-AUC, not ROC-AUC — the right metric under heavy imbalance
    "random_state": RANDOM_STATE,
    "n_jobs": -1,
}

# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------
POL_INPUT_PATH = "pol_scored_transactions.csv"
GRAPH_INPUT_PATH = "graph_scored_transactions.csv"
OUTPUT_PATH = "fusion_scored_transactions.csv"
MODEL_OUTPUT_PATH = "fusion_model.json"
SHAP_SUMMARY_PATH = "shap_feature_importance.csv"
