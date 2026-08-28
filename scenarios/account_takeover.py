import uuid

from entities.device import Device
from generators.transaction_generator import build_transaction
from utils.id_generator import generate_device_id


class AccountTakeoverScenario:
    """A victim's account is compromised: an unrecognized device/IP appears,
    followed shortly by a burst of high-value outbound transfers that drain
    a large share of the balance to accounts never paid before."""

    name = "account_takeover"

    def __init__(self, rng, config):
        self.rng = rng
        self.config = config

    def _rogue_device(self):
        return Device(
            device_id=generate_device_id(),
            device_type=self.rng.choice(self.config.DEVICE_TYPES),
            os_version=f"Android {self.rng.randint(9, 14)}.0",
            app_version=f"{self.rng.randint(1, 3)}.{self.rng.randint(0, 9)}.{self.rng.randint(0, 9)}",
            ip_address=".".join(str(self.rng.randint(1, 254)) for _ in range(4)),
            fingerprint=uuid.uuid4().hex,
        )

    def generate_incident(self, environment):
        victim = self.rng.choice(environment.accounts)
        pool = [a for a in environment.accounts if a.account_id != victim.account_id]
        rogue_device = self._rogue_device()
        session_id = f"ATO-{uuid.uuid4().hex[:8]}"

        takeover_time = self.rng.random_datetime(self.config.START_DATE, self.config.END_DATE)
        num_transfers = self.rng.randint(3, 6)
        remaining_balance = victim.balance
        elapsed = 0
        transactions = []

        for i in range(num_transfers):
            elapsed += self.rng.randint(30, 600)  # rapid-fire, minutes apart
            ts = self.rng.jitter_datetime(takeover_time, elapsed)
            receiver = self.rng.choice(pool)
            amount = min(
                remaining_balance * self.rng.uniform(0.15, 0.4),
                self.rng.lognormal_amount(mean=8.5, sigma=0.6, min_amount=2000, max_amount=100000),
            )
            remaining_balance = max(remaining_balance - amount, 0)

            transactions.append(
                build_transaction(
                    timestamp=ts,
                    sender_account=victim,
                    receiver_vpa=receiver.vpa,
                    receiver_account_id=receiver.account_id,
                    amount=amount,
                    transaction_type="P2P",
                    status="SUCCESS",
                    device=rogue_device,
                    is_fraud=True,
                    fraud_scenario=self.name,
                    session_id=session_id,
                    remarks="High-value transfer shortly after new device login",
                )
            )
        return transactions

    def generate(self, environment, num_incidents=None):
        num_incidents = num_incidents or self.config.FRAUD_SCENARIOS.get(self.name, 10)
        results = []
        for _ in range(num_incidents):
            results.extend(self.generate_incident(environment))
        return results
