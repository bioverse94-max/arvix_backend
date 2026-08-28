import argparse
from .pipeline import run_pol_pipeline

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="pol_scored_transactions.csv")
    args = parser.parse_args()

    df, baseline_df, eval_result = run_pol_pipeline(args.input, args.output)
    print(df[["transaction_id", "account_category", "pol_anomaly_score"]].sort_values(
        "pol_anomaly_score", ascending=False
    ).head(20))
    if eval_result:
        print(eval_result)
