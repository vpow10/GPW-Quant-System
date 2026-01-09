import numpy as np
import pandas as pd
import pytest

from strategies.momentum import MomentumStrategy


@pytest.fixture
def sample_data():
    dates = pd.date_range("2023-01-01", periods=20, freq="B")

    close = [100 * (1.01) ** i for i in range(20)]
    return pd.DataFrame({"date": dates, "close": close, "symbol": "TEST"})


def test_momentum_calculation(sample_data):
    lookback = 5
    strat = MomentumStrategy(lookback=lookback)
    df = strat.generate_signals(sample_data)

    assert "momentum" in df.columns
    expected = (1.01**5) - 1

    val = df["momentum"].iloc[5]
    assert np.isclose(val, expected)


def test_momentum_signals_long(sample_data):
    strat = MomentumStrategy(lookback=5, entry_long=0.05)
    df = strat.generate_signals(sample_data)

    # Should contain 1s
    assert 1 in df["signal"].unique()
    assert -1 not in df["signal"].unique()


def test_momentum_signals_short():
    dates = pd.date_range("2023-01-01", periods=20, freq="B")
    # Trend down
    close = [100 * (0.95) ** i for i in range(20)]
    df = pd.DataFrame({"date": dates, "close": close, "symbol": "TEST"})

    strat = MomentumStrategy(lookback=5, entry_short=-0.05)
    out = strat.generate_signals(df)

    # 0.95^5 - 1 ~= -0.22 < -0.05 -> Short
    assert -1 in out["signal"].unique()


def test_momentum_long_only():
    dates = pd.date_range("2023-01-01", periods=20, freq="B")
    close = [100 * (0.90) ** i for i in range(20)]
    df = pd.DataFrame({"date": dates, "close": close, "symbol": "TEST"})

    strat = MomentumStrategy(lookback=5, entry_short=-0.01, long_only=True)
    out = strat.generate_signals(df)

    assert -1 not in out["signal"].unique()
