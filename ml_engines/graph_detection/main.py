"""
main.py — Graph-Based Detection Module CLI entry point.

Usage:
    python main.py --input transactions.csv --output graph_scored_transactions.csv
"""

import argparse

from .pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(description="Graph-based UPI mule/fraud detection")
    parser.add_argument("--input", required=True, help="Path to input transactions CSV")
    parser.add_argument("--output", required=True, help="Path to write scored output CSV")
    args = parser.parse_args()

    run_pipeline(args.input, args.output)


if __name__ == "__main__":
    main()
