from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd


@dataclass
class BacktestConfig:
    """
    Global configuration for backtesting engine.

    All in wallet currency and in daily frequency.
    """

    initial_capital: float = 100_000.0

    commission_bps: float = 5.0  # bps = basis points; 5 bps = 0.05%
    slippage_bps: float = 2.0  # bps = basis points; 2 bps = 0.02%

    max_gross_leverage: float = 1.0  # max gross leverage allowed (e.g., 1.0 = 100%)

    trading_days_per_year: int = 252


@dataclass
class BacktestResult:
    """
    Result of backtest run.
    """

    # daily equity curve: columns [date, equity, cum_ret]
    equity_curve: pd.DataFrame

    # daily panel:
    # [date, symbol, ret_1d, gross_ret, net_ret, weight, weight_lag1, turnover, cost_ret]
    daily: pd.DataFrame

    # summary statistics
    summary: dict[str, Any]


@dataclass
class BacktestEngine:
    """
    Backtesting engine operating on historical daily data.

    Assumptions:
        - working on daily data (ret_1d = close_t / close{t-1} - 1)
        - signal 'signal' from day T is used as weight for day T+1 (no lookahead)
    """

    cfg: BacktestConfig

    def _prepare_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Prepare input DataFrame for backtesting.

        Input (per row):
            - 'symbol': instrument name
            - 'date': date
            - 'close': closing price
            - 'ret_1d': daily return close-to-close
            - 'signal': [-1, 0, 1] - directional signal

        Output:
            - sorted panel with additional columns:
                * 'weight': target weight based on signal
                * 'weight_lag1': lagged weight (used for turnover calculation), 1 day lag
        """
        required = {"date", "symbol", "close", "ret_1d", "signal"}
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"BacktestEngine: missing required columns: {missing}")

        out = df.copy()
        out["date"] = pd.to_datetime(out["date"])
        out["symbol"] = out["symbol"].str.lower()

        out = out.sort_values(["symbol", "date"]).reset_index(drop=True)

        out["weight"] = out["signal"].clip(-1, 1).astype(float)

        out["weight_lag1"] = out.groupby("symbol")["weight"].shift(1).fillna(0.0)

        return out

    def run_single_symbol(self, df: pd.DataFrame, symbol: str) -> BacktestResult:
        """
        Run backtest for a single symbol.
        """
        symbol = symbol.lower()
        panel = self._prepare_df(df[df["symbol"] == symbol])

        if panel.empty:
            raise ValueError(f"BacktestEngine: no data for symbol '{symbol}'")

        cost_per_turnover = (self.cfg.commission_bps + self.cfg.slippage_bps) / 10_000.0

        g = panel

        g["gross_ret"] = g["ret_1d"] * g["weight_lag1"]
        g["turnover"] = (g["weight"] - g["weight_lag1"]).abs()
        g["cost_ret"] = g["turnover"] * cost_per_turnover
        g["net_ret"] = g["gross_ret"] - g["cost_ret"]
        g["equity"] = self.cfg.initial_capital * (1.0 + g["net_ret"]).cumprod()
        g["cum_ret"] = g["equity"] / self.cfg.initial_capital - 1.0

        equity_curve = g[["date", "equity", "cum_ret"]].copy()

        daily = g[
            [
                "date",
                "symbol",
                "ret_1d",
                "gross_ret",
                "net_ret",
                "weight",
                "weight_lag1",
                "turnover",
                "cost_ret",
            ]
        ].copy()

        # --- metrics ---

        net_ret_series = (
            pd.Series(g["net_ret"], dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
        )

        if net_ret_series.empty:
            raise ValueError("BacktestEngine: no valid returns to compute metrics.")

        net_ret_arr: npt.NDArray[np.float64] = np.asarray(
            net_ret_series.to_numpy(), dtype=np.float64
        )
        n = int(net_ret_arr.shape[0])

        final_equity = float(equity_curve["equity"].iloc[-1])
        growth = final_equity / float(self.cfg.initial_capital)

        total_return = growth - 1.0
        years = n / float(self.cfg.trading_days_per_year)

        ann_ret = growth ** (1.0 / years) - 1.0

        ann_vol = float(net_ret_arr.std(ddof=0) * np.sqrt(self.cfg.trading_days_per_year))
        sharpe = ann_ret / ann_vol if ann_vol > 0.0 else float("nan")

        equity_series = (
            pd.Series(equity_curve["equity"], dtype="float64")
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        equity_arr: npt.NDArray[np.float64] = np.asarray(
            equity_series.to_numpy(), dtype=np.float64
        )
        curve = equity_arr / float(self.cfg.initial_capital)
        running_max = np.maximum.accumulate(curve)
        dd = curve / running_max - 1.0
        max_dd = float(dd.min().item())

        summary = {
            "symbol": symbol,
            "n_days": int(n),
            "initial_capital": float(self.cfg.initial_capital),
            "final_equity": final_equity,
            "total_return": float(total_return),
            "ann_return": float(ann_ret),
            "ann_vol": float(ann_vol),
            "sharpe": float(sharpe),
            "max_drawdown": max_dd,
        }

        return BacktestResult(
            equity_curve=equity_curve,
            daily=daily,
            summary=summary,
        )

    def run_portfolio(self, df: pd.DataFrame) -> BacktestResult:
        """
        Run a cross-sectional portfolio backtest using signals for many symbols.

        Idea:
            - for each date, collect signals across all symbols
            - normalize them into portfolio weights so that:
                * longs share 0.5 * max_gross_leverage
                * shorts share 0.5 * max_gross_leverage
            - use lagged portfolio weights to compute daily returns
            - apply transaction costs based on turnover in portfolio weights

        Parameters
        ----------
        df:
            DataFrame with at least:
                - 'symbol'
                - 'date'
                - 'ret_1d'
                - 'signal'
                - any other columns are passed through untouched

        Returns
        -------
        BacktestResult
            Portfolio equity curve, per-day portfolio stats, summary metrics.
        """
        panel = self._prepare_df(df)

        if panel.empty:
            raise ValueError("BacktestEngine: no data provided for portfolio backtest.")

        panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)

        cfg = self.cfg

        def _normalize_weights(group: pd.DataFrame) -> pd.DataFrame:
            longs = group["weight"] > 0.0
            shorts = group["weight"] < 0.0

            n_long = int(longs.sum())
            n_short = int(shorts.sum())

            w = pd.Series(0.0, index=group.index, dtype="float64")

            if n_long > 0 and n_short > 0:
                # symmetric long-short portfolio
                long_gross = 0.5 * cfg.max_gross_leverage
                short_gross = 0.5 * cfg.max_gross_leverage
            elif n_long > 0 and n_short == 0:
                # only long signals this day
                long_gross = cfg.max_gross_leverage
                short_gross = 0.0
            elif n_short > 0 and n_long == 0:
                # only short signals this day
                long_gross = 0.0
                short_gross = cfg.max_gross_leverage
            else:
                # no signals -> stay flat
                group["port_weight"] = w
                return group

            if n_long > 0:
                w.loc[longs] = long_gross / float(n_long)
            if n_short > 0:
                w.loc[shorts] = -short_gross / float(n_short)

            group["port_weight"] = w
            return group

        panel = panel.groupby("date", group_keys=False).apply(_normalize_weights)

        panel["port_weight_lag1"] = panel.groupby("symbol")["port_weight"].shift(1).fillna(0.0)

        cost_per_turnover = (cfg.commission_bps + cfg.slippage_bps) / 10_000.0
        g = panel
        g["symbol_gross_ret"] = g["ret_1d"] * g["port_weight_lag1"]
        g["symbol_turnover"] = (g["port_weight"] - g["port_weight_lag1"]).abs()
        g["symbol_cost_ret"] = g["symbol_turnover"] * cost_per_turnover

        grouped = panel.groupby("date", as_index=False).agg(
            gross_ret=("symbol_gross_ret", "sum"),
            cost_ret=("symbol_cost_ret", "sum"),
            gross_leverage=("port_weight_lag1", lambda w: float(w.abs().sum())),
            n_long=("port_weight_lag1", lambda w: int((w > 0.0).sum())),
            n_short=("port_weight_lag1", lambda w: int((w < 0.0).sum())),
            portfolio_turnover=("symbol_turnover", "sum"),
        )

        grouped["net_ret"] = grouped["gross_ret"] - grouped["cost_ret"]
        grouped["equity"] = cfg.initial_capital * (1.0 + grouped["net_ret"]).cumprod()
        grouped["cum_ret"] = grouped["equity"] / cfg.initial_capital - 1.0

        equity_curve = grouped[["date", "equity", "cum_ret"]].copy()
        daily = grouped.copy()

        # --- metrics ---

        net_ret_series = (
            pd.Series(daily["net_ret"], dtype="float64")
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        if net_ret_series.empty:
            raise ValueError("BacktestEngine: no valid returns to compute metrics.")

        net_ret_arr: npt.NDArray[np.float64] = np.asarray(
            net_ret_series.to_numpy(), dtype=np.float64
        )
        n = int(net_ret_arr.shape[0])

        growth = float(np.prod(1.0 + net_ret_arr))
        years = n / float(cfg.trading_days_per_year)
        ann_ret = growth ** (1.0 / years) - 1.0
        total_ret = growth - 1.0

        ann_vol = float(net_ret_arr.std(ddof=0) * np.sqrt(cfg.trading_days_per_year))
        sharpe = ann_ret / ann_vol if ann_vol > 0.0 else float("nan")

        equity_series = (
            pd.Series(daily["equity"], dtype="float64")
            .replace([np.inf, -np.inf], np.nan)
            .dropna()
        )
        equity_arr: npt.NDArray[np.float64] = np.asarray(
            equity_series.to_numpy(), dtype=np.float64
        )
        curve = equity_arr / float(cfg.initial_capital)
        running_max = np.maximum.accumulate(curve)
        dd = curve / running_max - 1.0
        max_dd = float(dd.min().item())

        avg_turnover = float(daily["portfolio_turnover"].mean())
        avg_gross_leverage = float(daily["gross_leverage"].mean())
        avg_n_long = float(daily["n_long"].mean())
        avg_n_short = float(daily["n_short"].mean())

        summary: dict[str, Any] = {
            "symbol": "PORTFOLIO",
            "n_days": int(n),
            "initial_capital": float(cfg.initial_capital),
            "final_equity": float(equity_curve["equity"].iloc[-1]),
            "total_return": float(total_ret),
            "ann_return": float(ann_ret),
            "ann_vol": float(ann_vol),
            "sharpe": float(sharpe),
            "max_drawdown": max_dd,
            "avg_turnover": avg_turnover,
            "avg_gross_leverage": avg_gross_leverage,
            "avg_n_long": avg_n_long,
            "avg_n_short": avg_n_short,
        }

        return BacktestResult(
            equity_curve=equity_curve,
            daily=daily,
            summary=summary,
        )
