import numpy as np
import pandas as pd
import pytest

from strategies.mean_reversion import MeanReversionStrategy


@pytest.fixture
def sample_data():
    dates = pd.date_range("2023-01-01", periods=50, freq="B")
    close = np.ones(50) * 100
    # Add a spike
    close[40] = 120  # Spike up
    close[45] = 80  # Spike down
    return pd.DataFrame({"date": dates, "close": close, "symbol": "TEST"})


def test_mr_signals(sample_data):
    # Window 20, z_entry 1.5
    strat = MeanReversionStrategy(window=20, z_entry=1.5)
    df = strat.generate_signals(sample_data)

    assert "zscore" in df.columns

    pass


def test_mr_with_noise():
    dates = pd.date_range("2023-01-01", periods=100, freq="B")
    np.random.seed(42)

    close = np.random.normal(100, 1, 100)

    close[90] = 110
    close[95] = 90

    df = pd.DataFrame({"date": dates, "close": close, "symbol": "TEST"})

    strat = MeanReversionStrategy(window=20, z_entry=2.0)
    out = strat.generate_signals(df)

    # Index 90: Close 110. MA around 100. Std around 1. Z ~ 10.
    # Z > 2 -> Short (-1).
    sig_90 = out["signal"].iloc[90]
    assert sig_90 == -1

    # Index 95: Close 90. MA around 100. Z ~ -10.
    # Z < -2 -> Long (1).
    sig_95 = out["signal"].iloc[95]
    assert sig_95 == 1


def test_mr_long_only_filtering():
    dates = pd.date_range("2023-01-01", periods=30, freq="B")
    close = np.ones(30) * 100
    close[25] = 120

    df = pd.DataFrame({"date": dates, "close": close, "symbol": "TEST"})

    strat_std = MeanReversionStrategy(window=10, z_entry=1.0)
    out_std = strat_std.generate_signals(df)
    strat_lo = MeanReversionStrategy(window=10, z_entry=1.0, long_only=True)
    out_lo = strat_lo.generate_signals(df)

    if -1 in out_std["signal"].values:
        assert -1 not in out_lo["signal"].values
