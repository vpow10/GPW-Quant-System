"""
Parse grid-search backtest summaries (the ALL_HYBRID_GRID_SUMMARIES_*.txt files) into a tidy table,
rank configurations, and generate a small set of plots.

Example:
    python -m data.scripts.analyze_hybrid_grid --inputs data/backtests/all_hybrids/ALL_HYBRID_GRID_SUMMARIES_*.txt --outdir data/backtests/all_hybrids/analysis_out

Outputs:
    - results.csv (all runs)
    - best_by_period.csv (best Sharpe per horizon/period/costs)
    - stability_rank.csv (configs ranked by average Sharpe across since_2015 and since_2020)
    - plots/*.png
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

STRATEGY_RE = re.compile(
    r"^=== Strategy:\s*(?P<strategy>[^|]+)\|\s*horizon=(?P<horizon>\d+)\s*\|\s*z-entry=(?P<z_entry>[-\d\.]+)\s*\|\s*min-hold=(?P<min_hold>\d+)\s*\|\s*vol-q=(?P<vol_q>[-\d\.]+)\s*\|\s*period=(?P<period>[^|]+)\s*\|\s*costs=(?P<costs>[^=]+)\s*===$"
)
METRIC_RE = re.compile(r"^\s*(?P<key>[a-zA-Z_]+)\s*:\s*(?P<val>[-+eE0-9\.naninf]+)\s*$")


def parse_summary_file(path: Path) -> pd.DataFrame:
    lines = path.read_text(errors="ignore").splitlines()
    rows: list[dict] = []
    cur: dict | None = None

    for line in lines:
        m = STRATEGY_RE.match(line.strip())
        if m:
            if cur is not None:
                rows.append(cur)
            cur = m.groupdict()
            cur["horizon"] = int(cur["horizon"])
            cur["z_entry"] = float(cur["z_entry"])
            cur["min_hold"] = int(cur["min_hold"])
            cur["vol_q"] = float(cur["vol_q"])
            cur["period"] = str(cur["period"]).strip()
            cur["costs"] = str(cur["costs"]).strip()
            cur["file"] = path.name
            continue

        if cur is None:
            continue

        mm = METRIC_RE.match(line)
        if mm:
            key = mm.group("key")
            val_s = mm.group("val")
            try:
                val = float(val_s)
            except Exception:
                val = float("nan")
            cur[key] = val

    if cur is not None:
        rows.append(cur)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    for c in [
        "ann_return",
        "ann_vol",
        "sharpe",
        "max_drawdown",
        "avg_turnover",
        "avg_gross_leverage",
        "avg_n_long",
        "avg_n_short",
        "final_equity",
        "total_return",
    ]:
        if c not in df.columns:
            df[c] = np.nan

    return df


def best_by(df: pd.DataFrame, group_cols: list[str], sort_col: str = "sharpe") -> pd.DataFrame:
    idx = df.groupby(group_cols)[sort_col].idxmax()
    return df.loc[idx].reset_index(drop=True)


def make_plots(df: pd.DataFrame, outdir: Path) -> None:
    plots = outdir / "plots"
    plots.mkdir(parents=True, exist_ok=True)

    sub = df[(df["costs"] == "realistic_5_2") & (df["period"] == "since_2020")].copy()
    if not sub.empty:
        plt.figure()
        plt.scatter(sub["avg_turnover"], sub["sharpe"])
        plt.xlabel("Average turnover (daily)")
        plt.ylabel("Sharpe")
        plt.title("Since 2020 (realistic costs): Sharpe vs turnover")
        plt.tight_layout()
        plt.savefig(plots / "since_2020_realistic_sharpe_vs_turnover.png", dpi=150)
        plt.close()

    for horizon in sorted(df["horizon"].dropna().unique().astype(int).tolist()):
        sub = df[
            (df["costs"] == "realistic_5_2")
            & (df["period"] == "since_2020")
            & (df["horizon"] == horizon)
            & (df["vol_q"] == 0.6)
        ].copy()
        if sub.empty:
            continue
        pivot = sub.pivot_table(index="z_entry", columns="min_hold", values="sharpe")
        plt.figure()
        plt.imshow(pivot.values, aspect="auto")
        plt.xticks(range(len(pivot.columns)), pivot.columns)
        plt.yticks(range(len(pivot.index)), pivot.index)
        plt.xlabel("min_hold (days)")
        plt.ylabel("z_entry")
        plt.title(f"Since 2020 realistic Sharpe heatmap (horizon={horizon}, vol_q=0.6)")
        plt.colorbar()
        plt.tight_layout()
        plt.savefig(plots / f"since_2020_realistic_sharpe_heatmap_h{horizon}_vq0.6.png", dpi=150)
        plt.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--inputs",
        nargs="+",
        required=True,
        help="One or more summary .txt files (globs supported by shell).",
    )
    ap.add_argument("--outdir", type=Path, default=Path("analysis_out"))
    args = ap.parse_args()

    outdir: Path = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)

    dfs = []
    for p in args.inputs:
        path = Path(p)
        if not path.exists():
            raise SystemExit(f"File not found: {path}")
        dfi = parse_summary_file(path)
        if not dfi.empty:
            dfs.append(dfi)

    if not dfs:
        raise SystemExit("No rows parsed. Check input files.")

    df = pd.concat(dfs, ignore_index=True)

    df.to_csv(outdir / "results.csv", index=False)

    best = best_by(df, ["horizon", "period", "costs"], "sharpe").sort_values(
        ["period", "horizon", "costs"]
    )
    best.to_csv(outdir / "best_by_period.csv", index=False)

    # stability rank: average Sharpe across since_2015 & since_2020 (realistic costs)
    sub = df[
        (df["costs"] == "realistic_5_2") & (df["period"].isin(["since_2015", "since_2020"]))
    ].copy()
    if not sub.empty:
        key = ["horizon", "z_entry", "min_hold", "vol_q"]
        piv = sub.pivot_table(index=key, columns="period", values="sharpe")
        piv["avg_sharpe_15_20"] = piv.mean(axis=1)
        piv = piv.reset_index().sort_values("avg_sharpe_15_20", ascending=False)
        piv.to_csv(outdir / "stability_rank.csv", index=False)

    make_plots(df, outdir)
    print(f"Wrote outputs to: {outdir.resolve()}")


if __name__ == "__main__":
    main()
