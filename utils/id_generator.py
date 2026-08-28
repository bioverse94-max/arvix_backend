import random
import string
import uuid


def generate_account_id():
    return "ACC" + "".join(random.choices(string.digits, k=10))


def generate_transaction_id():
    return "TXN" + uuid.uuid4().hex[:16].upper()


def generate_utr():
    """UPI transaction reference numbers are 12-digit numeric strings."""
    return "".join(random.choices(string.digits, k=12))


def generate_device_id():
    return "DEV" + uuid.uuid4().hex[:12].upper()


def generate_merchant_id():
    return "MER" + "".join(random.choices(string.digits, k=8))


def generate_vpa(name: str, bank_handle: str) -> str:
    slug = "".join(ch for ch in name.lower().replace(" ", ".") if ch.isalnum() or ch == ".")
    suffix = "".join(random.choices(string.digits, k=2))
    return f"{slug}{suffix}@{bank_handle}"
