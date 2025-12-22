from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from strategies.indicators import rsi, tsi

REPO_ROOT = Path(__file__).resolve().parents[1]

LAGS = 24

SEQ_GROUPS: List[List[str]] = [
    [f"log_return_lag{lag}" for lag in range(1, LAGS + 1)],
    [f"log_vol_chg_lag{lag}" for lag in range(1, LAGS + 1)],
    [f"rsi_14_lag{lag}" for lag in range(1, LAGS + 1)],
    [f"tsi_lag{lag}" for lag in range(1, LAGS + 1)],
]
SEQ_INPUT_SIZE = len(SEQ_GROUPS)

TAB_FEATURES = [
    "mom_signal",
    "mr_signal",
    "wig20_ret_1d",
    "wig20_mom_60d",
    "wig20_vol_20d",
    "wig20_rsi_14",
    "price_ma20_ratio",
    "price_ma50_ratio",
    "atr14_rel",
    "beta_60d",
]

REGIME_FEATURES = [
    "wig20_mom_60d",
    "wig20_vol_20d",
    "wig20_rsi_14",
]

TARGET_HORIZON = 10
TARGET = f"ret_{TARGET_HORIZON}d_log"

MOMENTUM_PATH = REPO_ROOT / "data" / "signals" / "momentum.parquet"
MEANREV_PATH = REPO_ROOT / "data" / "signals" / "mean_reversion.parquet"


def add_wig20_features(panel: pd.DataFrame, wig20_symbol: str = "wig20") -> pd.DataFrame:
    wig = panel[panel["symbol"].str.lower() == wig20_symbol].copy()
    if wig.empty:
        raise SystemExit("No wig20 data in combined panel. Fetch and preprocess wig20 first.")

    wig = wig.sort_values("date")
    wig["wig20_ret_1d"] = wig["close"].pct_change()
    wig["wig20_mom_60d"] = wig["wig20_ret_1d"].rolling(60).sum()
    wig["wig20_vol_20d"] = wig["wig20_ret_1d"].rolling(20).std()
    wig["wig20_rsi_14"] = rsi(wig["close"], window=14)

    cols = ["date", "wig20_ret_1d", "wig20_mom_60d", "wig20_vol_20d", "wig20_rsi_14"]
    wig_small = wig[cols].dropna()

    merged = panel.merge(wig_small, on="date", how="left")
    return merged


def add_stock_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").copy()

    df["ret_1d_log"] = np.log1p(df["ret_1d"])
    df["volume"] = df["volume"].replace(0, 1)
    df["vol_log"] = np.log(df["volume"])
    df["vol_log_chg"] = df["vol_log"].diff()

    # forward target for chosen horizon
    df[TARGET] = np.log(df["close"].shift(-TARGET_HORIZON) / df["close"])

    df["rsi_14"] = rsi(df["close"], window=14)
    df["tsi"] = tsi(df["close"])
    df["vol_20d"] = df["ret_1d_log"].rolling(20).std()

    df["ma_20"] = df["close"].rolling(20).mean()
    df["ma_50"] = df["close"].rolling(50).mean()
    df["price_ma20_ratio"] = df["close"] / df["ma_20"] - 1.0
    df["price_ma50_ratio"] = df["close"] / df["ma_50"] - 1.0

    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(14).mean()
    df["atr14_rel"] = df["atr_14"] / df["close"]

    if "wig20_ret_1d" in df.columns:
        cov = df["ret_1d"].rolling(60).cov(df["wig20_ret_1d"])
        var_mkt = df["wig20_ret_1d"].rolling(60).var()
        df["beta_60d"] = cov / var_mkt.replace(0.0, np.nan)
    else:
        df["beta_60d"] = np.nan

    lag_cols: dict[str, pd.Series] = {}
    for lag in range(1, LAGS + 1):
        lag_cols[f"log_return_lag{lag}"] = df["ret_1d_log"].shift(lag)
        lag_cols[f"log_vol_chg_lag{lag}"] = df["vol_log_chg"].shift(lag)
        lag_cols[f"rsi_14_lag{lag}"] = df["rsi_14"].shift(lag)
        lag_cols[f"tsi_lag{lag}"] = df["tsi"].shift(lag)

    lag_df = pd.DataFrame(lag_cols, index=df.index)
    df = pd.concat([df, lag_df], axis=1)

    return df


def build_seq_array(df: pd.DataFrame) -> np.ndarray:
    n = len(df)
    seq_array = np.zeros((n, LAGS, SEQ_INPUT_SIZE), dtype=np.float32)
    for j, group in enumerate(SEQ_GROUPS):
        seq_array[:, :, j] = df[group].to_numpy(dtype=np.float32)
    return seq_array


def merge_strategy_signals(panel: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()

    mom = pd.read_parquet(MOMENTUM_PATH)
    mr = pd.read_parquet(MEANREV_PATH)

    mom = mom.rename(columns={"signal": "mom_signal"})
    mr = mr.rename(columns={"signal": "mr_signal"})

    cols_base = ["symbol", "date"]
    panel = panel.merge(mom[cols_base + ["mom_signal"]], on=cols_base, how="left")
    panel = panel.merge(mr[cols_base + ["mr_signal"]], on=cols_base, how="left")

    return panel
