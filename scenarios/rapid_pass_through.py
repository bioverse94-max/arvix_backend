import uuid

from generators.transaction_generator import build_transaction


class RapidPassThroughScenario:
    """Money lands in an account and leaves again within minutes, almost
    the same amount minus a sliver -- the account is just a pass-through,
    not a genuine destination."""

    name = "rapid_pass_through"

    def __init__(self, rng, config):
        self.rng = rng
        self.config = config

    def generate_incident(self, environment):
        source, pass_through, destination = self.rng.sample(environment.accounts, 3)
        session_id = f"PASS-{uuid.uuid4().hex[:8]}"

        in_time = self.rng.random_datetime(self.config.START_DATE, self.config.END_DATE)
        amount = self.rng.lognormal_amount(mean=8.5, sigma=0.6, min_amount=10000, max_amount=150000)
        hold_seconds = self.rng.randint(30, 900)  # sits for under 15 minutes
        out_time = self.rng.jitter_datetime(in_time, hold_seconds)

        devices_in = environment.devices_for(source.account_id)
        devices_out = environment.devices_for(pass_through.account_id)

        txn_in = build_transaction(
            timestamp=in_time,
            sender_account=source,
            receiver_vpa=pass_through.vpa,
            receiver_account_id=pass_through.account_id,
            amount=amount,
            transaction_type="P2P",
            status="SUCCESS",
            device=self.rng.choice(devices_in) if devices_in else None,
            is_fraud=True,
            fraud_scenario=self.name,
            session_id=session_id,
            remarks="Incoming funds",
        )
        txn_out = build_transaction(
            timestamp=out_time,
            sender_account=pass_through,
            receiver_vpa=destination.vpa,
            receiver_account_id=destination.account_id,
            amount=amount * self.rng.uniform(0.95, 0.99),
            transaction_type="P2P",
            status="SUCCESS",
            device=self.rng.choice(devices_out) if devices_out else None,
            is_fraud=True,
            fraud_scenario=self.name,
            session_id=session_id,
            remarks="Outgoing funds shortly after receipt",
        )
        return [txn_in, txn_out]

    def generate(self, environment, num_incidents=None):
        num_incidents = num_incidents or self.config.FRAUD_SCENARIOS.get(self.name, 10)
        results = []
        for _ in range(num_incidents):
            results.extend(self.generate_incident(environment))
        return results
