"""
Run backtest for a given strategy and GPW symbol.

Example usage:
    run momentum on everything:
        python -m strategies.run_strategies \
        --input data/processed/reports/combined.parquet \
        --output-dir data/signals \
        --strategies momentum
    portfolio backtest of momentum strategy:
        python -m backtest.run_backtest \
        --signals data/signals/momentum.parquet \
        --mode portfolio \
        --initial-capital 100000 \
        --commission-bps 5 \
        --slippage-bps 5
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtest.engine import BacktestConfig, BacktestEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run backtest for a given strategy or for a cross-sectional portfolio."
    )
    parser.add_argument(
        "--signals",
        type=Path,
        required=True,
        help="Path to Parquet with strategy signals " "(output of strategies/run_strategies.py).",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Ticker/symbol to backtest (e.g. 'pzu'). Required if mode='single'.",
    )
    parser.add_argument(
        "--mode",
        choices=["single", "portfolio"],
        default="single",
        help="Backtest mode: 'single' (per symbol) or 'portfolio' (cross-sectional).",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=100_000.0,
        help="Initial capital in PLN.",
    )
    parser.add_argument(
        "--commission-bps",
        type=float,
        default=5.0,
        help=(
            "Broker commission in basis points of traded notional "
            "(per SIDE, not per roundtrip)."
        ),
    )
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=2.0,
        help="Slippage per SIDE in basis points of notional.",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Optional start date (YYYY-MM-DD). Data before this date is dropped.",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Optional end date (YYYY-MM-DD). Data after this date is dropped.",
    )

    args = parser.parse_args()

    if args.mode == "single" and not args.symbol:
        parser.error("--symbol is required when mode='single'")

    df = pd.read_parquet(args.signals)

    if args.start_date or args.end_date:
        if "date" not in df.columns:
            raise SystemExit("Input signals parquet is missing 'date' column.")
        df["date"] = pd.to_datetime(df["date"])

    if args.start_date:
        df = df[df["date"] >= args.start_date]

    if args.end_date:
        df = df[df["date"] <= args.end_date]

    if df.empty:
        raise SystemExit("No data left after applying date filters.")

    cfg = BacktestConfig(
        initial_capital=args.initial_capital,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
    )

    engine = BacktestEngine(cfg=cfg)

    if args.mode == "single":
        result = engine.run_single_symbol(df=df, symbol=args.symbol)
        tag = args.symbol.lower()
    else:
        result = engine.run_portfolio(df=df)
        tag = "portfolio"

    print("=== Backtest summary ===")  # noqa: T201
    for key, value in result.summary.items():
        print(f"{key:>16}: {value}")  # noqa: T201

    out_dir = Path("data/backtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / tag

    result.equity_curve.to_csv(prefix.with_suffix(".equity.csv"), index=False)
    result.daily.to_csv(prefix.with_suffix(".daily.csv"), index=False)


if __name__ == "__main__":
    main()
