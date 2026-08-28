"""
config.py — Graph-Based Detection Module
Mirrors the structure/philosophy of Pattern_of_life/config.py.

Column names, time windows, and model hyperparameters live here so nothing
is hardcoded deep inside the feature/model logic.
"""

# ---- Schema column names (must match transaction_schema.json) ----
COL_TXN_ID = "transaction_id"
COL_TIMESTAMP = "timestamp"
COL_SENDER_VPA = "sender_vpa"
COL_SENDER_ACCOUNT_ID = "sender_account_id"
COL_RECEIVER_VPA = "receiver_vpa"
COL_RECEIVER_ACCOUNT_ID = "receiver_account_id"
COL_AMOUNT = "amount"
COL_STATUS = "status"
COL_IS_FRAUD = "is_fraud"
COL_FRAUD_SCENARIO = "fraud_scenario"

# ---- Scoping decisions (same discipline as PoL Section 14) ----
# Only SUCCESS transactions actually move money -> only these build the graph.
VALID_STATUS = "SUCCESS"

# ---- Time windows ----
PASS_THROUGH_WINDOW_MIN = 60        # "forwarded within the hour" — Q1/Q5/Q6
FUNNEL_LOOKBACK_HOURS = 24          # window for in/out-degree, new-counterparty ratio
CYCLE_LOOKBACK_HOURS = 24           # window for circular_flow (round-trip) detection
MULTI_HOP_MAX_HOPS = 2              # how deep to trace downstream funnel convergence

# ---- Cold-start handling ----
# NOTE: this is intentionally much looser than the PoL module's cold-start
# rule (PoL Section 17.1 defaults any account with <30 rows to a score of 0,
# because its z-score features genuinely require a historical baseline to
# mean anything). Most of THIS module's features do not have that
# requirement: cycle_flag and pass_through_ratio are absolute, self-
# contained signals true or false at the moment they happen, regardless of
# how much history the account has — a brand-new account closing a 3-hop
# cycle is exactly the classic mule-ring shape, not noise to suppress.
# MIN_HISTORY_EDGES is kept low so cold-start only guards the genuinely
# uninformative case (an isolated account with no signal on either side),
# not the "small ring, few nodes, no other history" case that circular_flow
# and rapid_pass_through actually look like.
MIN_HISTORY_EDGES = 1
COLD_START_SCORE = 0.0

# ---- Structural thresholds used inside feature engineering ----
LAST_MILE_MIN_IN_DEGREE = 5         # candidate "terminal sink" needs at least this many senders
LAST_MILE_MAX_OUT_DEGREE = 1        # and almost nowhere further to forward to

# ---- Model hyperparameters ----
# Same philosophy as PoL Section 11/15: unsupervised, contamination left to
# sklearn's own data-driven heuristic — never set from the label ratio
# (that would be leakage-by-proxy, see PoL Section 15).
ISOLATION_FOREST_PARAMS = {
    "n_estimators": 200,
    "contamination": "auto",
    "random_state": 42,
    "n_jobs": -1,
}

# Category bucket fallback — same known gap as PoL Section 12.
# There is no declared account-category/KYC field in the schema, so every
# account currently falls into a single 'unclustered' bucket.
DEFAULT_CATEGORY = "unclustered"

# ---- Evaluation ----
TARGET_PRECISION = 0.80             # same evaluation bar used for the PoL module
