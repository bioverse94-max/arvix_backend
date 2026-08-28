import uuid

from generators.transaction_generator import build_transaction


class FanInScenario:
    """Many distinct accounts send money into a single 'collector' account
    within a short window -- a common signature of mule-fund aggregation."""

    name = "fan_in"

    def __init__(self, rng, config):
        self.rng = rng
        self.config = config

    def generate_incident(self, environment):
        collector = self.rng.choice(environment.accounts)
        pool = [a for a in environment.accounts if a.account_id != collector.account_id]
        num_senders = min(self.rng.randint(8, 20), len(pool))
        senders = self.rng.sample(pool, num_senders)
        session_id = f"FANIN-{uuid.uuid4().hex[:8]}"

        window_start = self.rng.random_datetime(self.config.START_DATE, self.config.END_DATE)
        transactions = []

        for sender in senders:
            devices = environment.devices_for(sender.account_id)
            device = self.rng.choice(devices) if devices else None
            ts = self.rng.jitter_datetime(window_start, self.rng.randint(0, 3600 * 6))
            amount = self.rng.lognormal_amount(mean=7.0, sigma=0.5, min_amount=1000, max_amount=20000)

            transactions.append(
                build_transaction(
                    timestamp=ts,
                    sender_account=sender,
                    receiver_vpa=collector.vpa,
                    receiver_account_id=collector.account_id,
                    amount=amount,
                    transaction_type="P2P",
                    status="SUCCESS",
                    device=device,
                    is_fraud=True,
                    fraud_scenario=self.name,
                    session_id=session_id,
                    remarks="Aggregation into collector account",
                )
            )
        return transactions

    def generate(self, environment, num_incidents=None):
        num_incidents = num_incidents or self.config.FRAUD_SCENARIOS.get(self.name, 10)
        results = []
        for _ in range(num_incidents):
            results.extend(self.generate_incident(environment))
        return results
