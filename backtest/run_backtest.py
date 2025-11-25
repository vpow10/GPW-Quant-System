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

import numpy as np
import pandas as pd

from backtest.engine import BacktestConfig, BacktestEngine


def main() -> None:  # noqa: C901
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
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=None,
        help=(
            "Optional path to benchmark price series (Parquet or CSV) "
            "with at least columns: 'date', 'close'. Used for comparison."
        ),
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

    if args.benchmark:
        if not args.benchmark.exists():
            raise SystemExit(f"Benchmark file not found: {args.benchmark}")

        if args.benchmark.suffix == ".parquet":
            bm_df = pd.read_parquet(args.benchmark)
        elif args.benchmark.suffix == ".csv":
            bm_df = pd.read_csv(args.benchmark)
        else:
            raise SystemExit("Benchmark file must be Parquet or CSV format.")

        if "date" not in bm_df.columns or "close" not in bm_df.columns:
            raise SystemExit("Benchmark file must contain 'date' and 'close' columns.")

        bm_df["date"] = pd.to_datetime(bm_df["date"])
        bm_df = bm_df.sort_values("date")

        bm_df["bm_ret"] = bm_df["close"].pct_change().fillna(0.0)

        daily = result.daily.copy()
        daily["date"] = pd.to_datetime(daily["date"])

        merged = pd.merge(
            daily[["date", "net_ret"]],
            bm_df[["date", "bm_ret"]],
            on="date",
            how="inner",
        )

        if merged.empty:
            raise SystemExit("No overlapping dates between backtest and benchmark.")

        merged["active_ret"] = merged["net_ret"] - merged["bm_ret"]

        def _ann_stats(r: pd.Series, trading_days: int) -> tuple[float, float, float]:
            r = r.replace([np.inf, -np.inf], np.nan).dropna()
            if r.empty:
                return float("nan"), float("nan"), float("nan")
            arr = r.to_numpy(dtype=np.float64)
            n = len(arr)
            growth = float(np.prod(1.0 + arr))
            years = n / float(trading_days)
            ann_ret = growth ** (1.0 / years) - 1.0
            ann_vol = float(arr.std(ddof=0) * np.sqrt(trading_days))
            sharpe = ann_ret / ann_vol if ann_vol > 0.0 else float("nan")
            return ann_ret, ann_vol, sharpe

        bench_ann_ret, bench_ann_vol, bench_sharpe = _ann_stats(
            merged["bm_ret"], engine.cfg.trading_days_per_year
        )
        active_ann_ret, active_ann_vol, active_sharpe = _ann_stats(
            merged["active_ret"], engine.cfg.trading_days_per_year
        )

    result.summary.update(
        {
            "bench_ann_return": float(bench_ann_ret),
            "bench_ann_vol": float(bench_ann_vol),
            "bench_sharpe": float(bench_sharpe),
            "active_ann_return": float(active_ann_ret),
            "active_ann_vol": float(active_ann_vol),
            "active_sharpe": float(active_sharpe),
        }
    )

    daily = pd.merge(
        daily,
        merged[["date", "bm_ret", "active_ret"]],
        on="date",
        how="left",
    )
    result.daily = daily

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
