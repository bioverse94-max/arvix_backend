import uuid

from generators.transaction_generator import build_transaction


class FanOutScenario:
    """A single account rapidly disperses money out to many distinct
    receivers, often in amounts kept just under common reporting
    thresholds -- a structuring/layering signature."""

    name = "fan_out"

    def __init__(self, rng, config):
        self.rng = rng
        self.config = config

    def generate_incident(self, environment):
        disperser = self.rng.choice(environment.accounts)
        pool = [a for a in environment.accounts if a.account_id != disperser.account_id]
        num_receivers = min(self.rng.randint(8, 20), len(pool))
        receivers = self.rng.sample(pool, num_receivers)
        session_id = f"FANOUT-{uuid.uuid4().hex[:8]}"

        window_start = self.rng.random_datetime(self.config.START_DATE, self.config.END_DATE)
        devices = environment.devices_for(disperser.account_id)
        device = self.rng.choice(devices) if devices else None

        transactions = []
        for receiver in receivers:
            ts = self.rng.jitter_datetime(window_start, self.rng.randint(0, 3600 * 6))
            amount = self.rng.uniform(30000, 49000)

            transactions.append(
                build_transaction(
                    timestamp=ts,
                    sender_account=disperser,
                    receiver_vpa=receiver.vpa,
                    receiver_account_id=receiver.account_id,
                    amount=amount,
                    transaction_type="P2P",
                    status="SUCCESS",
                    device=device,
                    is_fraud=True,
                    fraud_scenario=self.name,
                    session_id=session_id,
                    remarks="Dispersal from source account, structured amounts",
                )
            )
        return transactions

    def generate(self, environment, num_incidents=None):
        num_incidents = num_incidents or self.config.FRAUD_SCENARIOS.get(self.name, 10)
        results = []
        for _ in range(num_incidents):
            results.extend(self.generate_incident(environment))
        return results
