"""
Regime performance analysis for a backtest run.

Adds:
  - Strategy vs Benchmark vs Active metrics by regime (long + wide outputs)
  - Equity curves plot
  - Cost decomposition by regime (gross vs cost vs net)
  - Beta/alpha by regime (strategy vs benchmark)
  - Conditional metrics on INVESTED days (gross_leverage > threshold), to avoid "hit_rate" being diluted by zero-exposure days
  - "Arithmetic annualized mean" (mean_daily * 252) alongside CAGR-style annualized return

Inputs:
  - --daily-csv: output from backtest/run_backtest.py (e.g. data/backtests/portfolio.daily.csv)
  - --benchmark: benchmark price series (CSV or Parquet). Used for regime labeling (MA-based),
                 and as fallback bm_ret if daily-csv doesn't already contain bm_ret.

Benchmark schema supported:
  - ['date','close'] OR WIG20-style ['Data','Zamkniecie']

Outputs (in --outdir):
  - regime_metrics_long.csv
  - regime_metrics_wide.csv
  - plots/equity_curves.png
  - plots/regime_bar_ann_return.png
  - plots/regime_bar_sharpe_info.png
  - plots/regime_bar_turnover_leverage.png
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _clean_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def ann_stats_cagr(r: pd.Series, trading_days: int = 252) -> tuple[float, float, float]:
    """CAGR-style annualized return (geometric), annualized vol, Sharpe."""
    r = _clean_series(r)
    if r.empty:
        return float("nan"), float("nan"), float("nan")
    arr = r.to_numpy(dtype=np.float64)
    n = len(arr)
    growth = float(np.prod(1.0 + arr))
    years = n / float(trading_days)
    ann_ret = growth ** (1.0 / years) - 1.0
    ann_vol = float(arr.std(ddof=0) * np.sqrt(trading_days))
    sharpe = ann_ret / ann_vol if ann_vol > 0.0 else float("nan")
    return float(ann_ret), float(ann_vol), float(sharpe)


def ann_mean_arith(r: pd.Series, trading_days: int = 252) -> float:
    """Arithmetic annualized mean return: mean(daily) * trading_days."""
    r = _clean_series(r)
    if r.empty:
        return float("nan")
    return float(r.mean() * float(trading_days))


def max_drawdown(equity: pd.Series) -> float:
    equity = _clean_series(equity)
    if equity.empty:
        return float("nan")
    curve = equity.to_numpy(dtype=np.float64)
    running_max = np.maximum.accumulate(curve)
    dd = curve / running_max - 1.0
    return float(dd.min())


def beta_alpha(
    strategy_r: pd.Series, benchmark_r: pd.Series, trading_days: int = 252
) -> tuple[float, float]:
    """
    OLS beta and annualized alpha for: strategy_r = alpha + beta * benchmark_r + eps
    Alpha is annualized via alpha_daily * trading_days (approx).
    """
    df = pd.concat([_clean_series(strategy_r), _clean_series(benchmark_r)], axis=1).dropna()
    if df.shape[0] < 30:
        return float("nan"), float("nan")

    y = df.iloc[:, 0].to_numpy(dtype=np.float64)
    x = df.iloc[:, 1].to_numpy(dtype=np.float64)

    x_mean = x.mean()
    y_mean = y.mean()
    var_x = ((x - x_mean) ** 2).mean()
    if var_x <= 0.0:
        return float("nan"), float("nan")

    cov_xy = ((x - x_mean) * (y - y_mean)).mean()
    beta = cov_xy / var_x
    alpha_daily = y_mean - beta * x_mean
    alpha_ann = alpha_daily * float(trading_days)
    return float(beta), float(alpha_ann)


def _read_csv_flexible(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, sep=None, engine="python")
    except Exception:
        return pd.read_csv(path, sep=";")


def _load_benchmark_prices(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        bm = pd.read_parquet(path)
    else:
        bm = _read_csv_flexible(path)

    if {"date", "close"}.issubset(bm.columns):
        bm = bm[["date", "close"]].copy()
    elif {"Data", "Zamkniecie"}.issubset(bm.columns):
        bm = bm[["Data", "Zamkniecie"]].copy()
        bm = bm.rename(columns={"Data": "date", "Zamkniecie": "close"})
    else:
        raise SystemExit(
            "Benchmark must contain either columns ['date','close'] "
            "or WIG20 columns ['Data','Zamkniecie'].\n"
            f"Available columns: {bm.columns.tolist()}"
        )

    bm["date"] = pd.to_datetime(bm["date"], errors="coerce")
    bm["close"] = pd.to_numeric(bm["close"], errors="coerce")
    bm = bm.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return bm


def _masked_max_dd(returns: pd.Series, mask: pd.Series) -> float:
    r = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    r = r.where(mask, 0.0)
    eq = (1.0 + r).cumprod()
    return max_drawdown(eq)


def _compute_block(reg_df: pd.DataFrame, trading_days: int, invested_mask: pd.Series) -> dict:
    """
    Compute metrics for a return series in a given regime, plus conditional invested-day metrics.
    """
    out = {}

    ann_ret, ann_vol, sharpe = ann_stats_cagr(reg_df["r"], trading_days)
    out["ann_return"] = ann_ret
    out["ann_vol"] = ann_vol
    out["sharpe_or_ir"] = sharpe

    out["ann_mean_arith"] = ann_mean_arith(reg_df["r"], trading_days)

    r_clean = _clean_series(reg_df["r"])
    out["hit_rate"] = float((r_clean > 0).mean()) if not r_clean.empty else float("nan")

    inv = reg_df.loc[invested_mask, "r"]
    inv_clean = _clean_series(inv)
    out["hit_rate_invested"] = (
        float((inv_clean > 0).mean()) if not inv_clean.empty else float("nan")
    )
    out["ann_return_invested"], out["ann_vol_invested"], out["sharpe_invested"] = (
        ann_stats_cagr(inv_clean, trading_days)
        if not inv_clean.empty
        else (float("nan"), float("nan"), float("nan"))
    )
    out["ann_mean_arith_invested"] = ann_mean_arith(inv_clean, trading_days)

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily-csv", type=Path, required=True)
    ap.add_argument(
        "--benchmark", type=Path, required=True, help="CSV or Parquet with benchmark prices."
    )
    ap.add_argument("--outdir", type=Path, default=Path("regime_out"))
    ap.add_argument("--ma-window", type=int, default=200)
    ap.add_argument("--slope-window", type=int, default=20)
    ap.add_argument("--trading-days", type=int, default=252)
    ap.add_argument(
        "--invested-threshold",
        type=float,
        default=0.05,
        help="gross_leverage > threshold defines INVESTED days.",
    )
    args = ap.parse_args()

    outdir: Path = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    plots = outdir / "plots"
    plots.mkdir(parents=True, exist_ok=True)

    daily = pd.read_csv(args.daily_csv)
    if "date" not in daily.columns or "net_ret" not in daily.columns:
        raise SystemExit(
            f"Daily CSV must contain at least ['date','net_ret']. Available: {daily.columns.tolist()}"
        )

    daily["date"] = pd.to_datetime(daily["date"], errors="coerce")
    daily = daily.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    for c in [
        "gross_ret",
        "cost_ret",
        "gross_leverage",
        "portfolio_turnover",
        "n_long",
        "n_short",
        "bm_ret",
        "active_ret",
    ]:
        if c not in daily.columns:
            daily[c] = np.nan

    bm = _load_benchmark_prices(args.benchmark)
    bm["bm_ret_from_close"] = bm["close"].pct_change().fillna(0.0)
    bm["ma"] = bm["close"].rolling(args.ma_window).mean()
    bm["ma_slope"] = bm["ma"].diff(args.slope_window)

    m = pd.merge(
        daily,
        bm[["date", "close", "bm_ret_from_close", "ma", "ma_slope"]],
        on="date",
        how="inner",
    )
    if m.empty:
        raise SystemExit("No overlapping dates between daily and benchmark.")

    m["bm_ret_used"] = np.where(m["bm_ret"].notna(), m["bm_ret"], m["bm_ret_from_close"])
    m["active_ret_used"] = np.where(
        m["active_ret"].notna(), m["active_ret"], m["net_ret"] - m["bm_ret_used"]
    )

    bull = (m["close"] > m["ma"]) & (m["ma_slope"] > 0)
    bear = (m["close"] < m["ma"]) & (m["ma_slope"] < 0)
    m["regime"] = np.where(bull, "BULL", np.where(bear, "BEAR", "NORMAL"))

    m["equity_strategy"] = (
        1.0 + pd.to_numeric(m["net_ret"], errors="coerce").fillna(0.0)
    ).cumprod()
    m["equity_benchmark"] = (
        1.0 + pd.to_numeric(m["bm_ret_used"], errors="coerce").fillna(0.0)
    ).cumprod()
    m["equity_active"] = (
        1.0 + pd.to_numeric(m["active_ret_used"], errors="coerce").fillna(0.0)
    ).cumprod()

    plt.figure()
    plt.plot(m["date"], m["equity_strategy"], label="Strategy (net)")
    plt.plot(m["date"], m["equity_benchmark"], label="Benchmark (B&H)")
    plt.plot(m["date"], m["equity_active"], label="Active (strategy - benchmark)")
    plt.xlabel("Date")
    plt.ylabel("Equity (rebased)")
    plt.title("Equity curves (rebased to 1.0)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots / "equity_curves.png", dpi=150)
    plt.close()

    reg_order = ["BEAR", "NORMAL", "BULL"]
    series_defs = {
        "strategy_net": ("net_ret", None),
        "benchmark_bh": ("bm_ret_used", None),
        "active": ("active_ret_used", None),
    }

    rows = []
    for reg in reg_order:
        g = m[m["regime"] == reg].copy()
        if g.empty:
            continue

        invested = pd.to_numeric(g["gross_leverage"], errors="coerce").fillna(0.0) > float(
            args.invested_threshold
        )

        avg_gross_lev = float(pd.to_numeric(g["gross_leverage"], errors="coerce").mean())
        avg_turnover = float(pd.to_numeric(g["portfolio_turnover"], errors="coerce").mean())
        avg_n_long = float(pd.to_numeric(g["n_long"], errors="coerce").mean())
        avg_n_short = float(pd.to_numeric(g["n_short"], errors="coerce").mean())
        frac_invested = float(invested.mean())

        gross_ann_ret, _, _ = (
            ann_stats_cagr(g["gross_ret"], args.trading_days)
            if g["gross_ret"].notna().any()
            else (float("nan"), float("nan"), float("nan"))
        )
        cost_ann_ret, _, _ = (
            ann_stats_cagr(-g["cost_ret"], args.trading_days)
            if g["cost_ret"].notna().any()
            else (float("nan"), float("nan"), float("nan"))
        )

        beta_s, alpha_s = beta_alpha(g["net_ret"], g["bm_ret_used"], args.trading_days)

        clean = pd.concat(
            [_clean_series(g["net_ret"]), _clean_series(g["bm_ret_used"])],
            axis=1,
        )

        if clean.shape[0] >= 30:
            corr_sb = float(clean.corr().to_numpy(dtype=float)[0, 1])
        else:
            corr_sb = float("nan")

        for series_name, (col, _) in series_defs.items():
            reg_df = pd.DataFrame({"r": g[col]})
            met = _compute_block(reg_df, args.trading_days, invested_mask=invested)

            dd_masked = _masked_max_dd(g[col], m["regime"] == reg)

            row = {
                "regime": reg,
                "n_days": int(len(g)),
                "series": series_name,
                "ann_return": met["ann_return"],
                "ann_mean_arith": met["ann_mean_arith"],
                "ann_vol": met["ann_vol"],
                "sharpe_or_ir": met["sharpe_or_ir"],
                "max_drawdown_masked": dd_masked,
                "hit_rate": met["hit_rate"],
                "frac_invested": frac_invested,
                "hit_rate_invested": met["hit_rate_invested"],
                "ann_return_invested": met["ann_return_invested"],
                "ann_mean_arith_invested": met["ann_mean_arith_invested"],
                "ann_vol_invested": met["ann_vol_invested"],
                "sharpe_invested": met["sharpe_invested"],
                "avg_gross_leverage": avg_gross_lev,
                "avg_turnover": avg_turnover,
                "avg_n_long": avg_n_long,
                "avg_n_short": avg_n_short,
            }

            if series_name == "strategy_net":
                row.update(
                    beta=beta_s,
                    alpha_ann=alpha_s,
                    corr_with_benchmark=corr_sb,
                    ann_return_gross=gross_ann_ret,
                    ann_return_cost=cost_ann_ret,
                )
            elif series_name == "benchmark_bh":
                row.update(
                    beta=1.0,
                    alpha_ann=0.0,
                    corr_with_benchmark=1.0,
                    ann_return_gross=float("nan"),
                    ann_return_cost=float("nan"),
                )
            else:
                row.update(
                    beta=float("nan"),
                    alpha_ann=float("nan"),
                    corr_with_benchmark=float("nan"),
                    ann_return_gross=float("nan"),
                    ann_return_cost=float("nan"),
                )

            rows.append(row)

    metrics_long = pd.DataFrame(rows).sort_values(["regime", "series"]).reset_index(drop=True)
    metrics_long.to_csv(outdir / "regime_metrics_long.csv", index=False)

    wide = metrics_long.pivot_table(
        index=[
            "regime",
            "n_days",
            "avg_gross_leverage",
            "avg_turnover",
            "avg_n_long",
            "avg_n_short",
            "frac_invested",
        ],
        columns="series",
        values=[
            "ann_return",
            "ann_mean_arith",
            "ann_vol",
            "sharpe_or_ir",
            "max_drawdown_masked",
            "hit_rate",
            "hit_rate_invested",
            "ann_return_invested",
            "ann_mean_arith_invested",
            "ann_vol_invested",
            "sharpe_invested",
            "beta",
            "alpha_ann",
            "corr_with_benchmark",
            "ann_return_gross",
            "ann_return_cost",
        ],
        aggfunc=lambda s: s.iloc[0] if len(s) else np.nan,
    )
    mi = cast(pd.MultiIndex, wide.columns)
    wide.columns = [f"{t[0]}__{t[1]}" for t in mi.to_flat_index()]
    wide = wide.reset_index().sort_values("regime")
    wide.to_csv(outdir / "regime_metrics_wide.csv", index=False)

    plot_df = metrics_long[
        metrics_long["series"].isin(["strategy_net", "benchmark_bh", "active"])
    ].copy()
    plot_df["regime"] = pd.Categorical(plot_df["regime"], categories=reg_order, ordered=True)
    plot_df = plot_df.sort_values(["regime", "series"])

    x = np.arange(len(reg_order))
    series_order = ["strategy_net", "benchmark_bh", "active"]
    width = 0.25

    plt.figure()
    for i, s in enumerate(series_order):
        sub = plot_df[plot_df["series"] == s].set_index("regime").reindex(reg_order)
        plt.bar(x + (i - 1) * width, sub["ann_return"].to_numpy(), width, label=s)
    plt.xticks(x, reg_order)
    plt.xlabel("Regime")
    plt.ylabel("Annualized return (CAGR-style)")
    plt.title("Annualized return by regime (strategy vs benchmark vs active)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots / "regime_bar_ann_return.png", dpi=150)
    plt.close()

    plt.figure()
    for i, s in enumerate(series_order):
        sub = plot_df[plot_df["series"] == s].set_index("regime").reindex(reg_order)
        plt.bar(x + (i - 1) * width, sub["sharpe_or_ir"].to_numpy(), width, label=s)
    plt.xticks(x, reg_order)
    plt.xlabel("Regime")
    plt.ylabel("Sharpe (strategy/benchmark) or IR (active)")
    plt.title("Risk-adjusted performance by regime")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots / "regime_bar_sharpe_info.png", dpi=150)
    plt.close()

    strat_only = metrics_long[metrics_long["series"] == "strategy_net"].copy()
    strat_only["regime"] = pd.Categorical(
        strat_only["regime"], categories=reg_order, ordered=True
    )
    strat_only = strat_only.sort_values("regime")

    plt.figure()
    plt.bar(
        x - width / 2,
        strat_only["avg_gross_leverage"].to_numpy(),
        width,
        label="avg_gross_leverage",
    )
    plt.bar(x + width / 2, strat_only["avg_turnover"].to_numpy(), width, label="avg_turnover")
    plt.xticks(x, reg_order)
    plt.xlabel("Regime")
    plt.title("Exposure and turnover by regime (strategy)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(plots / "regime_bar_turnover_leverage.png", dpi=150)
    plt.close()

    print(f"Wrote outputs to: {outdir.resolve()}")


if __name__ == "__main__":
    main()
