"""
Run backtest for a given strategy and GPW symbol.

Example usage:
    python -m backtest.run_backtest \
        --signals data/signals/momentum.parquet \
        --symbol pzu \
        --initial-capital 100000 \
        --commission-bps 10 \
        --slippage-bps 5
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from backtest.engine import BacktestConfig, BacktestEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run backtest for a given strategy and GPW symbol."
    )
    parser.add_argument(
        "--signals",
        type=Path,
        required=True,
        help="Path to Parquet with strategy signals " "(output of strategies/run_strategy.py).",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        required=True,
        help="Ticker/symbol to backtest (e.g. 'pzu').",
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
        help="Broker commission in basis points of traded notional (per side).",
    )
    parser.add_argument(
        "--slippage-bps",
        type=float,
        default=2.0,
        help="Slippage per trade in basis points of notional (per side).",
    )

    args = parser.parse_args()

    df = pd.read_parquet(args.signals)

    cfg = BacktestConfig(
        initial_capital=args.initial_capital,
        commission_bps=args.commission_bps,
        slippage_bps=args.slippage_bps,
    )

    engine = BacktestEngine(cfg=cfg)
    result = engine.run_single_symbol(df=df, symbol=args.symbol)

    print("=== Backtest summary ===")  # noqa: T201
    for key, value in result.summary.items():
        print(f"{key:>16}: {value}")  # noqa: T201

    out_dir = Path("data/backtests")
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / f"{args.symbol.lower()}"

    result.equity_curve.to_csv(prefix.with_suffix(".equity.csv"), index=False)
    result.daily.to_csv(prefix.with_suffix(".daily.csv"), index=False)


if __name__ == "__main__":
    main()
