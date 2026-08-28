TXN_ID_COL = "transaction_id"
SENDER_COL = "sender_account_id"
RECEIVER_COL = "receiver_account_id"
SENDER_VPA_COL = "sender_vpa"
RECEIVER_VPA_COL = "receiver_vpa"
AMOUNT_COL = "amount"
TIMESTAMP_COL = "timestamp"
STATUS_COL = "status"
VALID_STATUS_VALUES = ["SUCCESS"]
LABEL_COL = "is_fraud"
LEAKAGE_COLS = ["is_fraud", "fraud_scenario"]
CATEGORY_COL = "account_category"

VELOCITY_WINDOWS_MIN = [10, 30, 60]
DIVERSITY_WINDOWS_DAYS = [7, 30]
PASS_THROUGH_WINDOW_MIN = 60
BASELINE_MIN_HISTORY_DAYS = 14

ISO_FOREST_CONTAMINATION = "auto"
ISO_FOREST_N_ESTIMATORS = 200
ISO_FOREST_RANDOM_STATE = 42

DEFAULT_CATEGORY = "unclustered"
CATEGORY_LIST = ["personal", "merchant", "salaried", "student", "gig_worker", DEFAULT_CATEGORY]
