import numpy as np
import pandas as pd
import pytest

from strategies.config_strategies import STRATEGY_CONFIG, STRATEGY_REGISTRY


@pytest.fixture
def sample_df():
    # Create sufficient data for lookbacks up to 252 days
    dates = pd.date_range("2020-01-01", periods=300, freq="B")

    # Random walk with drift
    np.random.seed(42)
    returns = np.random.normal(0.0005, 0.01, size=len(dates))
    price = 100 * np.cumprod(1 + returns)

    df = pd.DataFrame({"date": dates, "close": price, "symbol": ["TEST"] * len(dates)})
    return df


@pytest.mark.parametrize("strategy_name", STRATEGY_REGISTRY.keys())
def test_strategy_instantiation_and_signals(strategy_name, sample_df):
    """
    Smoke test: Ensure every registered strategy can:
    1. Be instantiated with its config.
    2. Generate signals on sample data without crashing.
    3. Return a DataFrame with expected columns.
    """

    if "lstm" in strategy_name:
        pass

    cls = STRATEGY_REGISTRY[strategy_name]
    config = STRATEGY_CONFIG.get(strategy_name, {})

    # Instantiate
    try:
        strategy = cls(**config)
    except Exception as e:
        pytest.fail(f"Failed to instantiate {strategy_name}: {e}")

    # Generate Signals
    try:
        out = strategy.generate_signals(sample_df)
    except FileNotFoundError:
        if "lstm" in strategy_name:
            pytest.skip("LSTM model file not found, skipping test.")
        raise
    except Exception as e:
        pytest.fail(f"Strategy {strategy_name} crashed on signal generation: {e}")

    # Checks
    assert isinstance(out, pd.DataFrame)
    assert len(out) == len(sample_df)
    assert "signal" in out.columns
