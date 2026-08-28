"""
main.py — CLI entry point for the fusion engine.

Usage:
    python main.py \
        --pol pol_scored_transactions.csv \
        --graph graph_scored_transactions.csv \
        --output fusion_scored_transactions.csv
"""

import argparse
from .pipeline import run_pipeline
from .config import POL_INPUT_PATH, GRAPH_INPUT_PATH, OUTPUT_PATH


def main():
    parser = argparse.ArgumentParser(description="UPI Fraud Detection — Fusion Layer")
    parser.add_argument("--pol", default=POL_INPUT_PATH,
                         help="Path to pol_scored_transactions.csv (output of the PoL module)")
    parser.add_argument("--graph", default=GRAPH_INPUT_PATH,
                         help="Path to graph_scored_transactions.csv (output of the Graph module)")
    parser.add_argument("--output", default=OUTPUT_PATH,
                         help="Path to write the final fused, scored output CSV")
    args = parser.parse_args()

    run_pipeline(pol_path=args.pol, graph_path=args.graph, output_path=args.output)


if __name__ == "__main__":
    main()
