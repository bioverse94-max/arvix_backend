"""CLI entry point: builds a synthetic population, generates normal UPI
traffic, injects labeled fraud scenarios, and writes the combined dataset.

Examples:
    python main.py
    python main.py --accounts 500 --normal-transactions 5000 --format json
    python main.py --scenarios mule_network circular_flow --seed 7
"""
import argparse
import os
import sys

from config.config import Config
from generators.environment_generator import EnvironmentGenerator
from generators.transaction_generator import TransactionGenerator
from output.csv_writer import CSVWriter
from output.json_writer import JSONWriter
from output.stream_writer import StreamWriter
from scenarios.account_takeover import AccountTakeoverScenario
from scenarios.circular_flow import CircularFlowScenario
from scenarios.fan_in import FanInScenario
from scenarios.fan_out import FanOutScenario
from scenarios.mule_network import MuleNetworkScenario
from scenarios.rapid_pass_through import RapidPassThroughScenario
from utils.random_utils import RandomProvider

SCENARIO_REGISTRY = {
    "account_takeover": AccountTakeoverScenario,
    "mule_network": MuleNetworkScenario,
    "fan_in": FanInScenario,
    "fan_out": FanOutScenario,
    "rapid_pass_through": RapidPassThroughScenario,
    "circular_flow": CircularFlowScenario,
}

# Expected transactions per incident for each scenario, derived analytically
# from the randint()/sample() ranges each scenario uses internally (e.g.
# account_takeover does randint(3, 6) transfers per incident -> avg 4.5).
# Used only to convert a target --fraud-ratio into incident counts up front;
# actual output will vary slightly since generation is still fully random.
SCENARIO_AVG_TXNS = {
    "account_takeover": 4.5,
    "mule_network": 3.5,
    "fan_in": 14,
    "fan_out": 14,
    "rapid_pass_through": 2,
    "circular_flow": 4,
}


def parse_args():
    parser = argparse.ArgumentParser(description="Synthetic UPI transaction dataset generator")
    parser.add_argument("--accounts", type=int, default=Config.NUM_ACCOUNTS)
    parser.add_argument("--merchants", type=int, default=Config.NUM_MERCHANTS)
    parser.add_argument("--normal-transactions", type=int, default=Config.NUM_NORMAL_TRANSACTIONS)
    parser.add_argument("--seed", type=int, default=Config.RANDOM_SEED)
    parser.add_argument("--output-dir", type=str, default=Config.OUTPUT_DIR)
    parser.add_argument("--format", choices=["csv", "json", "jsonl"], default="csv")
    parser.add_argument(
        "--scenarios",
        nargs="*",
        default=list(SCENARIO_REGISTRY.keys()),
        help="Which fraud scenarios to inject (default: all)",
    )
    parser.add_argument(
        "--stream", action="store_true", help="Also print the final dataset as a simulated JSON-lines stream"
    )
    parser.add_argument(
        "--fraud-ratio",
        type=float,
        default=None,
        metavar="0-1",
        help=(
            "Target fraction of the final dataset that should be fraudulent, e.g. 0.01 for "
            "~1%%. When set, overrides Config.FRAUD_SCENARIOS -- incident counts are scaled "
            "(keeping their default relative proportions across the selected --scenarios) to "
            "approximate this ratio. Omit to use the raw incident counts in Config instead."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()

    class RunConfig(Config):
        NUM_ACCOUNTS = args.accounts
        NUM_MERCHANTS = args.merchants
        NUM_NORMAL_TRANSACTIONS = args.normal_transactions
        OUTPUT_DIR = args.output_dir

    rng = RandomProvider(seed=args.seed)

    print(f"Building environment: {RunConfig.NUM_ACCOUNTS} accounts, {RunConfig.NUM_MERCHANTS} merchants...")
    env = EnvironmentGenerator(rng, RunConfig).build()

    print(f"Generating {RunConfig.NUM_NORMAL_TRANSACTIONS} normal transactions...")
    transactions = TransactionGenerator(rng, RunConfig).generate_normal(env, RunConfig.NUM_NORMAL_TRANSACTIONS)

    scenario_incident_counts = {name: RunConfig.FRAUD_SCENARIOS.get(name, 10) for name in args.scenarios}

    if args.fraud_ratio is not None:
        if not (0 <= args.fraud_ratio < 1):
            print("--fraud-ratio must be in [0, 1)", file=sys.stderr)
            sys.exit(1)

        # Solve fraud / (normal + fraud) = ratio for fraud, given normal is fixed.
        target_fraud_txns = args.fraud_ratio * RunConfig.NUM_NORMAL_TRANSACTIONS / (1 - args.fraud_ratio)

        base_weights = {name: RunConfig.FRAUD_SCENARIOS.get(name, 10) for name in args.scenarios}
        total_weight = sum(base_weights.values()) or 1

        scenario_incident_counts = {}
        for name, weight in base_weights.items():
            share_of_fraud_txns = target_fraud_txns * (weight / total_weight)
            avg_txns = SCENARIO_AVG_TXNS.get(name, 5)
            incidents = round(share_of_fraud_txns / avg_txns)
            scenario_incident_counts[name] = max(incidents, 1) if target_fraud_txns > 0 else 0

        print(
            f"Targeting ~{args.fraud_ratio:.2%} fraud (~{round(target_fraud_txns)} fraud transactions) "
            f"-> incident counts: {scenario_incident_counts}"
        )

    for name in args.scenarios:
        scenario_cls = SCENARIO_REGISTRY.get(name)
        if not scenario_cls:
            print(f"  ! Unknown scenario '{name}', skipping", file=sys.stderr)
            continue
        count = scenario_incident_counts.get(name, 0)
        if count <= 0:
            continue
        print(f"Generating fraud scenario '{name}' ({count} incidents)...")
        scenario_txns = scenario_cls(rng, RunConfig).generate(env, num_incidents=count)
        transactions.extend(scenario_txns)
        print(f"  -> {len(scenario_txns)} transactions")

    rng.shuffle(transactions)

    os.makedirs(RunConfig.OUTPUT_DIR, exist_ok=True)
    if args.format == "csv":
        out_path = os.path.join(RunConfig.OUTPUT_DIR, "transactions.csv")
        CSVWriter.write(transactions, out_path)
    elif args.format == "json":
        out_path = os.path.join(RunConfig.OUTPUT_DIR, "transactions.json")
        JSONWriter.write(transactions, out_path)
    else:
        out_path = os.path.join(RunConfig.OUTPUT_DIR, "transactions.jsonl")
        JSONWriter.write_jsonl(transactions, out_path)

    fraud_count = sum(1 for t in transactions if t["is_fraud"])
    total = len(transactions)
    print(f"\nDone. {total} total transactions written to {out_path}")
    print(f"  {fraud_count} fraudulent ({fraud_count / total:.2%}), {total - fraud_count} normal")

    if args.stream:
        print("\nStreaming transactions...\n")
        StreamWriter().stream(transactions)


if __name__ == "__main__":
    main()
