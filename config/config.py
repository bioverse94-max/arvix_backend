"""Central configuration for the synthetic UPI dataset generator."""
from datetime import datetime


class Config:
    RANDOM_SEED = 42

    NUM_ACCOUNTS = 2000
    NUM_MERCHANTS = 150
    NUM_NORMAL_TRANSACTIONS = 20000

    START_DATE = datetime(2026, 1, 1)
    END_DATE = datetime(2026, 6, 30)

    # Each "incident" is one full occurrence of the fraud pattern (e.g. one
    # mule chain, one account-takeover episode). Each incident produces
    # several transactions grouped by a shared session_id.
    FRAUD_SCENARIOS = {
        "account_takeover": 25,
        "mule_network": 15,
        "fan_in": 20,
        "fan_out": 20,
        "rapid_pass_through": 30,
        "circular_flow": 15,
    }

    BANK_HANDLES = [
        ("State Bank of India", "oksbi"),
        ("HDFC Bank", "okhdfcbank"),
        ("ICICI Bank", "okicici"),
        ("Axis Bank", "okaxis"),
        ("Punjab National Bank", "okpnb"),
        ("Paytm Payments Bank", "paytm"),
        ("Yes Bank", "ybl"),
        ("Kotak Mahindra Bank", "kotak"),
    ]

    CITIES = [
        ("Mumbai", "Maharashtra"),
        ("Bengaluru", "Karnataka"),
        ("Delhi", "Delhi"),
        ("Hyderabad", "Telangana"),
        ("Chennai", "Tamil Nadu"),
        ("Pune", "Maharashtra"),
        ("Kolkata", "West Bengal"),
        ("Ahmedabad", "Gujarat"),
        ("Jaipur", "Rajasthan"),
        ("Lucknow", "Uttar Pradesh"),
    ]

    MCC_CATEGORIES = [
        ("5411", "Grocery Stores"),
        ("5812", "Restaurants"),
        ("5732", "Electronics"),
        ("4111", "Transport"),
        ("5912", "Pharmacy"),
        ("5651", "Apparel"),
        ("4899", "Utilities"),
        ("6300", "Insurance"),
        ("8299", "Education"),
        ("5999", "Miscellaneous Retail"),
    ]

    DEVICE_TYPES = ["Android", "iOS"]

    OUTPUT_DIR = "data/generated"
