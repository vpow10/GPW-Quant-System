import glob
import os
import warnings

import pandas as pd
import pytest

SIGNAL_DIR = "data/signals"


def get_signal_files():
    files = glob.glob(os.path.join(SIGNAL_DIR, "*.parquet"))
    return files


@pytest.mark.parametrize("file_path", get_signal_files())
def test_signal_file_integrity(file_path):
    """
    Verify that generated signal files:
    1. Can be loaded.
    2. Have required columns.
    3. Have non-constant signals (unless empty or specific edge case).
    """
    try:
        df = pd.read_parquet(file_path)
    except Exception as e:
        pytest.fail(f"Failed to read parquet file {file_path}: {e}")

    required_cols = ["date", "symbol", "close", "signal"]
    missing = [c for c in required_cols if c not in df.columns]
    assert not missing, f"Missing columns in {file_path}: {missing}"

    if df.empty:
        pytest.skip(f"Signal file {file_path} is empty.")

    unique_signals = df["signal"].unique()

    if len(unique_signals) <= 1:
        val = unique_signals[0]
        if val == 0:
            pytest.fail(
                f"Strategy {file_path} produced ONLY FLAT (0) signals. Check parameters or logic."
            )
        else:
            warnings.warn(
                f"Strategy {file_path} produced CONSTANT signal {val}. Is this intended?"
            )
            pytest.fail(f"Strategy {file_path} produced CONSTANT signal {val}. (Invariant)")
