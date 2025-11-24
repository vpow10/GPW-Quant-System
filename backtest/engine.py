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

        total_ret = float(np.prod(1.0 + net_ret_arr))
        years = n / float(self.cfg.trading_days_per_year)

        ann_ret = (1.0 + total_ret) ** (1.0 / years) - 1.0

        ann_vol = float(net_ret_arr.std(ddof=0) * np.sqrt(self.cfg.trading_days_per_year))
        sharpe = ann_ret / ann_vol if ann_vol > 0.0 else float("nan")

        equity_series = (
            pd.Series(g["equity"], dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
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
            "final_equity": float(equity_curve["equity"].iloc[-1]),
            "total_return": float(equity_curve["cum_ret"].iloc[-1]),
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
