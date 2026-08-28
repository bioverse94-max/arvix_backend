from config.config import Config
from generators.account_generator import AccountGenerator
from utils.random_utils import RandomProvider


def test_account_generation_basic():
    rng = RandomProvider(seed=1)
    accounts = AccountGenerator(rng, Config).generate(10)

    assert len(accounts) == 10
    for acc in accounts:
        assert "@" in acc.vpa
        assert acc.balance >= 0
        assert acc.account_id.startswith("ACC")
        assert acc.account_type in {"SAVINGS", "CURRENT"}
