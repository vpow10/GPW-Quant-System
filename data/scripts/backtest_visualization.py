"""
CSV equity/return plotter.

- Loads a CSV with at least: date, equity, cum_ret (optional), net_ret (optional)
- Plots:
  1) Equity over time with an initial-capital dashed baseline (default: 100,000)
     Equity line is green when >= baseline and red when < baseline.
  2) Cumulative return (if available), otherwise cumulative product of (1+net_ret).

Usage:
  python plot_strategy.py path/to/results.csv
  python plot_strategy.py path/to/results.csv --initial 100000 --out path/to/equity.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib as mpl
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.ticker import FuncFormatter, PercentFormatter


def set_professional_mpl_style() -> None:
    mpl.rcParams.update(
        {
            "figure.dpi": 120,
            "savefig.dpi": 300,
            "figure.figsize": (12, 7),
            "font.size": 11,
            "axes.titlesize": 14,
            "axes.labelsize": 11,
            "axes.titleweight": "semibold",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.linestyle": "-",
            "axes.axisbelow": True,
            "legend.frameon": False,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "xtick.major.size": 4,
            "ytick.major.size": 4,
            "lines.linewidth": 2.0,
        }
    )


def money_fmt(x, _pos) -> str:
    return f"{x:,.0f}"


def load_data(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    if "date" not in df.columns:
        raise ValueError("CSV must contain a 'date' column.")
    if "equity" not in df.columns:
        raise ValueError("CSV must contain an 'equity' column.")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    df["equity"] = pd.to_numeric(df["equity"], errors="coerce")
    df = df.dropna(subset=["equity"]).reset_index(drop=True)

    if "cum_ret" in df.columns:
        df["cum_ret"] = pd.to_numeric(df["cum_ret"], errors="coerce")
    elif "net_ret" in df.columns:
        df["net_ret"] = pd.to_numeric(df["net_ret"], errors="coerce").fillna(0.0)
        df["cum_ret"] = (1.0 + df["net_ret"]).cumprod() - 1.0
    else:
        df["cum_ret"] = np.nan

    return df


def equity_colored_line(ax, x_dates, equity, baseline: float) -> None:
    x = mdates.date2num(pd.to_datetime(x_dates))
    y = np.asarray(equity, dtype=float)

    points = np.array([x, y]).T.reshape(-1, 1, 2)
    segs = np.concatenate([points[:-1], points[1:]], axis=1)

    above = y[1:] >= baseline
    colors = np.where(above, "#1a7f37", "#b42318")  # green / red

    lc = LineCollection(segs, colors=colors, linewidths=2.2, capstyle="round", joinstyle="round")
    ax.add_collection(lc)
    ax.set_xlim(x.min(), x.max())
    ax.set_ylim(min(y.min(), baseline) * 0.995, max(y.max(), baseline) * 1.005)


def plot(df: pd.DataFrame, initial: float, out_path: Path | None) -> None:
    set_professional_mpl_style()

    fig = plt.figure(constrained_layout=True)
    gs = fig.add_gridspec(2, 1, height_ratios=[2.2, 1.2])

    ax_eq = fig.add_subplot(gs[0, 0])
    ax_ret = fig.add_subplot(gs[1, 0], sharex=ax_eq)

    equity_colored_line(ax_eq, df["date"], df["equity"], baseline=initial)
    ax_eq.axhline(
        initial,
        color="0.35",
        linestyle=(0, (4, 4)),
        linewidth=1.5,
        label=f"Initial capital ({initial:,.0f})",
    )

    ax_eq.set_title("Strategy Equity Curve vs. Initial Capital")
    ax_eq.set_ylabel("Equity")
    ax_eq.yaxis.set_major_formatter(FuncFormatter(money_fmt))

    last_date = df["date"].iloc[-1]
    last_eq = float(df["equity"].iloc[-1])
    pnl = last_eq - initial
    pnl_pct = (last_eq / initial - 1.0) if initial != 0 else np.nan
    ax_eq.annotate(
        f"Last: {last_eq:,.0f}  |  PnL: {pnl:,.0f} ({pnl_pct:+.2%})",
        xy=(mdates.date2num(last_date), last_eq),
        xytext=(12, 10),
        textcoords="offset points",
        ha="left",
        va="bottom",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.25", "fc": "white", "ec": "0.85", "alpha": 0.95},
    )

    ax_eq.legend(loc="upper left")

    if df["cum_ret"].notna().any():
        ax_ret.plot(df["date"], df["cum_ret"], linewidth=2.0)
        ax_ret.axhline(0.0, color="0.5", linewidth=1.0)
        ax_ret.set_ylabel("Cumulative return")
        ax_ret.yaxis.set_major_formatter(PercentFormatter(xmax=1.0))
        ax_ret.set_title("Cumulative Return")
    else:
        ax_ret.text(
            0.01,
            0.5,
            "No cumulative return available (missing 'cum_ret' and 'net_ret').",
            transform=ax_ret.transAxes,
            ha="left",
            va="center",
        )
        ax_ret.set_axis_off()

    ax_ret.set_xlabel("Date")
    locator = mdates.AutoDateLocator(minticks=6, maxticks=10)
    ax_ret.xaxis.set_major_locator(locator)
    ax_ret.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))

    plt.setp(ax_eq.get_xticklabels(), visible=False)

    if out_path:
        fig.savefig(out_path, bbox_inches="tight")
    else:
        plt.show()


def main() -> None:
    p = argparse.ArgumentParser(description="Plot equity and returns from a strategy CSV.")
    p.add_argument("csv", type=Path, help="Path to CSV file.")
    p.add_argument(
        "--initial",
        type=float,
        default=100_000.0,
        help="Initial capital baseline (default: 100000).",
    )
    p.add_argument(
        "--out", type=Path, default=None, help="Optional output image path (e.g., equity.png)."
    )
    args = p.parse_args()

    df = load_data(args.csv)
    plot(df, initial=args.initial, out_path=args.out)


if __name__ == "__main__":
    main()
