import uuid

from generators.transaction_generator import build_transaction


class CircularFlowScenario:
    """Funds travel A -> B -> C -> ... and back to A, a closed loop that
    inflates apparent transaction volume without any real economic
    activity (wash-trading style behaviour)."""

    name = "circular_flow"

    def __init__(self, rng, config):
        self.rng = rng
        self.config = config

    def generate_incident(self, environment):
        loop_length = self.rng.randint(3, 5)
        loop = self.rng.sample(environment.accounts, loop_length)
        session_id = f"CIRC-{uuid.uuid4().hex[:8]}"

        current_time = self.rng.random_datetime(self.config.START_DATE, self.config.END_DATE)
        amount = self.rng.lognormal_amount(mean=8.0, sigma=0.4, min_amount=5000, max_amount=80000)

        transactions = []
        for i in range(loop_length):
            sender = loop[i]
            receiver = loop[(i + 1) % loop_length]
            devices = environment.devices_for(sender.account_id)
            device = self.rng.choice(devices) if devices else None
            current_time = self.rng.jitter_datetime(current_time, self.rng.randint(300, 3600))
            hop_amount = amount * self.rng.uniform(0.97, 1.0)

            transactions.append(
                build_transaction(
                    timestamp=current_time,
                    sender_account=sender,
                    receiver_vpa=receiver.vpa,
                    receiver_account_id=receiver.account_id,
                    amount=hop_amount,
                    transaction_type="P2P",
                    status="SUCCESS",
                    device=device,
                    is_fraud=True,
                    fraud_scenario=self.name,
                    session_id=session_id,
                    remarks=f"Circular flow hop {i + 1}/{loop_length}",
                )
            )
        return transactions

    def generate(self, environment, num_incidents=None):
        num_incidents = num_incidents or self.config.FRAUD_SCENARIOS.get(self.name, 10)
        results = []
        for _ in range(num_incidents):
            results.extend(self.generate_incident(environment))
        return results
