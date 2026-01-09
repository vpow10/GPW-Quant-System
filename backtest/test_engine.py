from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import BacktestConfig, BacktestEngine


def _toy_flat_panel(n_days: int = 10) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": ["test"] * n_days,
            "close": 100.0,
            "ret_1d": 0.0,  # no price change
            "signal": 0,  # no position
        }
    )


def test_flat_strategy_keeps_capital() -> None:
    df = _toy_flat_panel(n_days=20)
    cfg = BacktestConfig(initial_capital=50_000.0, commission_bps=0.0, slippage_bps=0.0)
    engine = BacktestEngine(cfg=cfg)

    res = engine.run_single_symbol(df=df, symbol="test")

    assert len(res.equity_curve) == 20
    assert res.equity_curve["equity"].iloc[0] == 50_000.0
    assert abs(res.equity_curve["equity"].iloc[-1] - 50_000.0) < 1e-6


def test_always_long_on_constant_returns() -> None:
    n_days = 10
    dates = pd.date_range("2020-01-01", periods=n_days, freq="B")

    df = pd.DataFrame(
        {
            "date": dates,
            "symbol": ["test"] * n_days,
            "close": 100.0,
            "ret_1d": 0.01,  # +1% close-to-close
            "signal": 1,  # always long
        }
    )

    cfg = BacktestConfig(initial_capital=100_000.0, commission_bps=0.0, slippage_bps=0.0)
    engine = BacktestEngine(cfg=cfg)

    res = engine.run_single_symbol(df=df, symbol="test")

    # On the first day we have no exposure (weight_lag1 = 0),
    # so effectively we have 9 days at +1% on the capital.
    expected = 100_000.0 * (1.01 ** (n_days - 1))

    assert np.isclose(res.equity_curve["equity"].iloc[-1], expected, rtol=1e-6)
