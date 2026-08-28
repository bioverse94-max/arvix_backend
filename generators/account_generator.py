from datetime import timedelta

from faker import Faker

from entities.account import Account
from utils.id_generator import generate_account_id, generate_vpa


class AccountGenerator:
    def __init__(self, rng, config):
        self.rng = rng
        self.config = config
        self.faker = Faker("en_IN")

    def generate(self, n: int):
        accounts = []
        for _ in range(n):
            name = self.faker.name()
            bank_name, handle = self.rng.choice(self.config.BANK_HANDLES)
            created_at = self.config.START_DATE - timedelta(days=self.rng.randint(30, 1500))

            account = Account(
                account_id=generate_account_id(),
                holder_name=name,
                vpa=generate_vpa(name, handle),
                bank_name=bank_name,
                ifsc=f"{handle[:4].upper()}0{self.rng.randint(100000, 999999)}",
                account_type=self.rng.weighted_choice(["SAVINGS", "CURRENT"], [0.85, 0.15]),
                balance=round(
                    self.rng.lognormal_amount(mean=9.0, sigma=1.2, min_amount=200, max_amount=500000), 2
                ),
                created_at=created_at,
                risk_score=round(self.rng.uniform(0, 0.15), 3),
                status="ACTIVE",
            )
            accounts.append(account)
        return accounts
