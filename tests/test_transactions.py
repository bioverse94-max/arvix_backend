from config.config import Config
from generators.environment_generator import EnvironmentGenerator
from generators.transaction_generator import TransactionGenerator
from utils.random_utils import RandomProvider


class _SmallConfig(Config):
    NUM_ACCOUNTS = 20
    NUM_MERCHANTS = 5


def test_normal_transaction_generation():
    rng = RandomProvider(seed=2)
    env = EnvironmentGenerator(rng, _SmallConfig).build()
    txns = TransactionGenerator(rng, _SmallConfig).generate_normal(env, 50)

    assert len(txns) == 50
    for t in txns:
        assert t["amount"] > 0
        assert t["is_fraud"] is False
        assert t["status"] in {"SUCCESS", "FAILED", "PENDING"}
        assert t["sender_vpa"] != t["receiver_vpa"]
