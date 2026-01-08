import numpy as np
import pandas as pd
import pytest

from strategies.rsi import RSIStrategy


@pytest.fixture
def sample_data():
    dates = pd.date_range("2023-01-01", periods=20, freq="B")
    # Price pattern that creates RSI swings
    close = [
        100,
        105,
        110,
        115,
        120,
        125,
        130,  # Rise (RSI High)
        125,
        120,
        115,
        110,
        105,
        100,
        95,  # Fall (RSI Low)
        100,
        105,
        110,
        115,
        120,
        125,  # Rise again
    ]
    return pd.DataFrame({"date": dates, "close": close[: len(dates)]})


def test_rsi_calculation(sample_data):
    # RSI period 5 for testing sensitivity
    strat = RSIStrategy(period=5)
    df = strat.generate_signals(sample_data)

    assert "rsi" in df.columns
    # Check RSI bounds
    assert df["rsi"].min() >= 0
    assert df["rsi"].max() <= 100

    # Check NaN handling for initial period
    assert np.isnan(df["rsi"].iloc[0])


def test_rsi_standard_signals(sample_data):
    # Standard: Long < 30, Short > 70
    strat = RSIStrategy(period=5, lower_bound=30, upper_bound=70, long_only=False)
    df = strat.generate_signals(sample_data)

    sig_vals = df["signal"].unique()
    assert 0 in sig_vals
    oversold = df[df["rsi"] < 30]
    if not oversold.empty:
        idx = oversold.index[0]
        assert df["signal"].iloc[idx] == 1


def test_rsi_long_only_exit():
    df = pd.DataFrame({"close": np.random.randn(100)})  # placeholder
    df["rsi"] = np.nan

    rsi_vals = [50] * 10 + [20] + [40] * 9 + [60] + [50] * 5
    df = pd.DataFrame({"rsi": rsi_vals, "close": 100})

    prices = [100.0]
    for _ in range(10):
        prices.append(prices[-1] * 0.98)  # Down -> Low RSI
    for _ in range(10):
        prices.append(prices[-1] * 1.02)  # Up -> High RSI

    df = pd.DataFrame({"close": prices})

    strat = RSIStrategy(
        period=5, lower_bound=30, upper_bound=70, exit_long_level=50, long_only=True
    )

    out = strat.generate_signals(df)

    assert -1 not in out["signal"].unique()
    assert 1 in out["signal"].unique()


def test_rsi_parameter_passthrough():
    strat = RSIStrategy(period=10, exit_long_level=55)
    assert strat.params["period"] == 10
    assert strat.params["exit_long_level"] == 55
