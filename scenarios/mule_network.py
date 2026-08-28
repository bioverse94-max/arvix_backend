import uuid

from generators.transaction_generator import build_transaction


class MuleNetworkScenario:
    """Funds move through a chain of 'mule' accounts (A -> B -> C -> ...),
    each hop happening quickly and each mule passing on nearly the full
    amount minus a small cut, until the money reaches a final account."""

    name = "mule_network"

    def __init__(self, rng, config):
        self.rng = rng
        self.config = config

    def generate_incident(self, environment):
        chain_length = self.rng.randint(3, 6)
        chain = self.rng.sample(environment.accounts, chain_length)
        session_id = f"MULE-{uuid.uuid4().hex[:8]}"

        current_time = self.rng.random_datetime(self.config.START_DATE, self.config.END_DATE)
        current_amount = self.rng.lognormal_amount(mean=9.0, sigma=0.5, min_amount=20000, max_amount=300000)

        transactions = []
        for i in range(chain_length - 1):
            sender, receiver = chain[i], chain[i + 1]
            devices = environment.devices_for(sender.account_id)
            device = self.rng.choice(devices) if devices else None

            fee_cut = self.rng.uniform(0.01, 0.05)  # mule keeps a small cut
            outgoing = current_amount * (1 - fee_cut)
            current_time = self.rng.jitter_datetime(current_time, self.rng.randint(60, 1800))

            transactions.append(
                build_transaction(
                    timestamp=current_time,
                    sender_account=sender,
                    receiver_vpa=receiver.vpa,
                    receiver_account_id=receiver.account_id,
                    amount=outgoing,
                    transaction_type="P2P",
                    status="SUCCESS",
                    device=device,
                    is_fraud=True,
                    fraud_scenario=self.name,
                    session_id=session_id,
                    remarks=f"Layer {i + 1} of mule chain",
                )
            )
            current_amount = outgoing
        return transactions

    def generate(self, environment, num_incidents=None):
        num_incidents = num_incidents or self.config.FRAUD_SCENARIOS.get(self.name, 10)
        results = []
        for _ in range(num_incidents):
            results.extend(self.generate_incident(environment))
        return results
