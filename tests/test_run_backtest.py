from pathlib import Path

import pandas as pd
import pytest

from backtest.run_backtest import run_single_backtest


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary directory with dummy signal and benchmark files."""
    d = tmp_path / "data"
    d.mkdir()

    dates = pd.date_range("2023-01-01", periods=10, freq="B")
    df_sig = pd.DataFrame(
        {
            "date": dates,
            "symbol": "test",
            "close": 100.0,
            "ret_1d": 0.0,
            "signal": [1, 1, 1, 0, 0, -1, -1, 0, 1, 1],
        }
    )
    sig_path = d / "signals.parquet"
    df_sig.to_parquet(sig_path)

    df_bm = pd.DataFrame({"date": dates, "close": [100 * (1.001**i) for i in range(10)]})
    bm_path = d / "benchmark.parquet"
    df_bm.to_parquet(bm_path)

    return d, sig_path, bm_path


def test_run_single_backtest_execution(temp_data_dir, tmp_path):
    """
    Test that run_single_backtest:
    1. Reads the inputs.
    2. Runs the backtest.
    3. Writes the output CSVs.
    """
    data_dir, sig_path, bm_path = temp_data_dir

    symbol = "TEST"
    tag = symbol.lower()

    run_single_backtest(
        signals_path=sig_path,
        mode="single",
        initial_capital=10000,
        commission_bps=0,
        slippage_bps=0,
        symbol=symbol,
        benchmark=bm_path,
    )

    out_dir = Path("data/backtests")
    out_equity = out_dir / f"{tag}.equity.csv"
    out_daily = out_dir / f"{tag}.daily.csv"

    assert out_equity.exists()
    assert out_daily.exists()

    res = pd.read_csv(out_daily)
    assert not res.empty
    assert "net_ret" in res.columns
    assert "bm_ret" in res.columns

    if out_equity.exists():
        out_equity.unlink()
    if out_daily.exists():
        out_daily.unlink()


def test_run_backtest_missing_file():
    with pytest.raises(FileNotFoundError):
        run_single_backtest(
            signals_path=Path("non_existent.parquet"),
            mode="single",
            initial_capital=10000,
            commission_bps=0,
            slippage_bps=0,
            symbol="TEST",
        )
