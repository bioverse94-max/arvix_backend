from .data_prep import load_and_prepare
from .baseline import build_account_baselines
from .features import build_pol_features
from .model import attach_category, score_pattern_of_life, evaluate_threshold


def run_pol_pipeline(csv_path, output_path=None):
    df, accounts = load_and_prepare(csv_path)
    baseline_df = build_account_baselines(df)
    df = build_pol_features(df, baseline_df)
    df = attach_category(df, baseline_df)
    df = score_pattern_of_life(df)
    eval_result = evaluate_threshold(df)

    if output_path:
        df.to_csv(output_path, index=False)

    return df, baseline_df, eval_result
