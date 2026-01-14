import importlib.util

import numpy as np
import pandas as pd
import pytest

from strategies.config_strategies import STRATEGY_CONFIG, get_strategy_class


def _is_ml_strategy(name: str) -> bool:
    return "lstm" in name.lower()


def _torch_available() -> bool:
    return importlib.util.find_spec("torch") is not None


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """
    Sufficient data for lookbacks up to ~252 business days.
    Deterministic random walk so the test is stable.
    """
    dates = pd.date_range("2020-01-01", periods=300, freq="B")
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0005, 0.01, size=len(dates))
    price = 100 * np.cumprod(1 + returns)

    return pd.DataFrame(
        {
            "date": dates,
            "close": price,
            "symbol": ["TEST"] * len(dates),
        }
    )


@pytest.mark.parametrize("strategy_name", sorted(STRATEGY_CONFIG.keys()))
def test_strategy_instantiation_and_signals(strategy_name: str, sample_df: pd.DataFrame) -> None:
    """
    Smoke test: for every configured strategy (non-ML by default),
    ensure it can be instantiated and can generate signals without crashing.
    """
    # Default CI behavior: skip ML strategies unless torch is installed
    if _is_ml_strategy(strategy_name) and not _torch_available():
        pytest.skip("Skipping ML strategies because torch is not installed.")

    # Resolve class lazily (avoids importing ML deps unless needed)
    try:
        cls = get_strategy_class(strategy_name)
    except KeyError:
        pytest.fail(
            f"Strategy '{strategy_name}' is in STRATEGY_CONFIG but not resolvable by registry."
        )

    config = STRATEGY_CONFIG.get(strategy_name, {})

    try:
        strategy = cls(**config) if config else cls()
    except Exception as e:
        pytest.fail(f"Failed to instantiate {strategy_name}: {e}")

    try:
        out = strategy.generate_signals(sample_df)
    except FileNotFoundError as e:
        pytest.skip(f"Missing required file for {strategy_name}: {e}")
    except ModuleNotFoundError as e:
        pytest.skip(f"Optional dependency missing for {strategy_name}: {e}")
    except Exception as e:
        pytest.fail(f"Strategy {strategy_name} crashed on signal generation: {e}")

    assert isinstance(out, pd.DataFrame)
    assert len(out) == len(sample_df)
    assert "signal" in out.columns

    sig = pd.to_numeric(out["signal"], errors="coerce")
    assert sig.notna().all(), "signal column contains non-numeric values"
    assert np.isfinite(sig.to_numpy()).all(), "signal column contains non-finite values"
