from utils.id_generator import generate_transaction_id, generate_utr
from utils.time_utils import iso


def build_transaction(
    timestamp,
    sender_account,
    receiver_vpa,
    receiver_account_id,
    amount,
    transaction_type="P2P",
    status="SUCCESS",
    device=None,
    is_fraud=False,
    fraud_scenario=None,
    session_id=None,
    remarks="",
):
    """Single source of truth for the transaction record schema. Every
    generator and every scenario builds records through this function so
    the output is always consistent -- see data/schemas/transaction_schema.json."""
    return {
        "transaction_id": generate_transaction_id(),
        "utr": generate_utr(),
        "timestamp": iso(timestamp),
        "sender_vpa": sender_account.vpa,
        "sender_account_id": sender_account.account_id,
        "receiver_vpa": receiver_vpa,
        "receiver_account_id": receiver_account_id,
        "amount": round(amount, 2),
        "currency": "INR",
        "transaction_type": transaction_type,
        "channel": "UPI",
        "status": status,
        "device_id": device.device_id if device else None,
        "ip_address": device.ip_address if device else None,
        "remarks": remarks,
        "is_fraud": is_fraud,
        "fraud_scenario": fraud_scenario,
        "session_id": session_id,
    }


class TransactionGenerator:
    """Generates ordinary, non-fraudulent P2P and P2M UPI traffic to form
    the background against which the scenarios in scenarios/ inject
    labeled fraud patterns."""

    def __init__(self, rng, config):
        self.rng = rng
        self.config = config

    def generate_normal(self, environment, n: int):
        transactions = []
        accounts = environment.accounts
        merchants = environment.merchants

        for _ in range(n):
            is_p2m = bool(merchants) and self.rng.boolean(0.4)

            if is_p2m:
                sender = self.rng.choice(accounts)
                receiver = self.rng.choice(merchants)
                devices = environment.devices_for(sender.account_id)
                device = self.rng.choice(devices) if devices else None

                txn = build_transaction(
                    timestamp=self.rng.random_datetime(self.config.START_DATE, self.config.END_DATE),
                    sender_account=sender,
                    receiver_vpa=receiver.vpa,
                    receiver_account_id=receiver.merchant_id,
                    amount=self.rng.lognormal_amount(mean=5.5, sigma=0.9, min_amount=10, max_amount=15000),
                    transaction_type="P2M",
                    status=self.rng.weighted_choice(["SUCCESS", "FAILED", "PENDING"], [0.95, 0.04, 0.01]),
                    device=device,
                    remarks=f"Payment to {receiver.category}",
                )
            else:
                sender, receiver = self.rng.sample(accounts, 2)
                devices = environment.devices_for(sender.account_id)
                device = self.rng.choice(devices) if devices else None

                txn = build_transaction(
                    timestamp=self.rng.random_datetime(self.config.START_DATE, self.config.END_DATE),
                    sender_account=sender,
                    receiver_vpa=receiver.vpa,
                    receiver_account_id=receiver.account_id,
                    amount=self.rng.lognormal_amount(mean=6.5, sigma=1.1, min_amount=10, max_amount=100000),
                    transaction_type="P2P",
                    status=self.rng.weighted_choice(["SUCCESS", "FAILED", "PENDING"], [0.95, 0.04, 0.01]),
                    device=device,
                    remarks="",
                )
            transactions.append(txn)
        return transactions
