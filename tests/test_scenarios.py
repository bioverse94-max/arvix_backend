from config.config import Config
from generators.environment_generator import EnvironmentGenerator
from scenarios.account_takeover import AccountTakeoverScenario
from scenarios.circular_flow import CircularFlowScenario
from scenarios.fan_in import FanInScenario
from scenarios.fan_out import FanOutScenario
from scenarios.mule_network import MuleNetworkScenario
from scenarios.rapid_pass_through import RapidPassThroughScenario
from utils.random_utils import RandomProvider


class _SmallConfig(Config):
    NUM_ACCOUNTS = 50
    NUM_MERCHANTS = 5


def _env(seed=3):
    rng = RandomProvider(seed=seed)
    env = EnvironmentGenerator(rng, _SmallConfig).build()
    return rng, env


def test_account_takeover():
    rng, env = _env()
    txns = AccountTakeoverScenario(rng, _SmallConfig).generate(env, num_incidents=2)
    assert all(t["is_fraud"] for t in txns)
    assert all(t["fraud_scenario"] == "account_takeover" for t in txns)


def test_mule_network():
    rng, env = _env()
    txns = MuleNetworkScenario(rng, _SmallConfig).generate(env, num_incidents=2)
    assert all(t["is_fraud"] for t in txns)


def test_fan_in_and_fan_out():
    rng, env = _env()
    fan_in_txns = FanInScenario(rng, _SmallConfig).generate(env, num_incidents=1)
    fan_out_txns = FanOutScenario(rng, _SmallConfig).generate(env, num_incidents=1)
    assert len(fan_in_txns) >= 5
    assert len(fan_out_txns) >= 5


def test_rapid_pass_through():
    rng, env = _env()
    txns = RapidPassThroughScenario(rng, _SmallConfig).generate(env, num_incidents=2)
    assert len(txns) == 4  # 2 incidents x 2 legs each


def test_circular_flow():
    rng, env = _env()
    txns = CircularFlowScenario(rng, _SmallConfig).generate(env, num_incidents=2)
    assert all(t["is_fraud"] for t in txns)
    session_ids = {t["session_id"] for t in txns}
    assert len(session_ids) == 2
