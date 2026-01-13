from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from strategies.config_strategies import STRATEGY_CONFIG, get_strategy_class


def run_strategies(
    strategy_names: list[str],
    input_path: Path,
    output_dir: Path,
) -> None:
    df = pd.read_parquet(input_path)

    output_dir.mkdir(parents=True, exist_ok=True)

    for name in strategy_names:
        try:
            strategy_cls = get_strategy_class(name)
        except KeyError:
            continue

        params = STRATEGY_CONFIG.get(name, {})
        strategy = strategy_cls(**params) if params else strategy_cls()

        signals = strategy.generate_signals(df)

        # 1) pełny Parquet
        parquet_path = output_dir / f"{name}.parquet"
        signals.to_parquet(parquet_path, index=False)

        # 2) CSV bez params (czytelniejszy)
        csv_path = output_dir / f"{name}.csv"
        signals_no_params = signals.drop(columns=["params"], errors="ignore")
        signals_no_params.to_csv(csv_path, index=False)

        # 3) light CSV z najważniejszymi kolumnami
        light_cols = ["symbol", "date"]
        for c in ["close", "momentum", "zscore", "signal"]:
            if c in signals_no_params.columns:
                light_cols.append(c)

        light = signals_no_params[light_cols]
        light_path = output_dir / f"{name}_light.csv"
        light.to_csv(light_path, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one or more strategies on GPW data.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/reports/combined.parquet"),
        help="Path to input parquet with historical data.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/signals"),
        help="Directory where signals will be saved.",
    )

    all_names = list(STRATEGY_CONFIG.keys())
    parser.add_argument(
        "--strategies",
        "-s",
        nargs="+",
        choices=all_names,
        default=all_names,
        help="Which strategies to run (default: all).",
    )

    args = parser.parse_args()

    run_strategies(
        strategy_names=args.strategies,
        input_path=args.input,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
