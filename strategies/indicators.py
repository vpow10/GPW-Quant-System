import numpy as np
import pandas as pd


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.rolling(window).mean()
    roll_down = down.rolling(window).mean()
    rs = roll_up / roll_down.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out


def tsi(close: pd.Series, r: int = 25, s: int = 13) -> pd.Series:
    m = close.diff()
    ema1 = m.ewm(span=r, adjust=False).mean()
    ema2 = ema1.ewm(span=s, adjust=False).mean()

    abs_m = m.abs()
    ema1_abs = abs_m.ewm(span=r, adjust=False).mean()
    ema2_abs = ema1_abs.ewm(span=s, adjust=False).mean()

    tsi_raw = 100.0 * ema2 / ema2_abs.replace(0.0, np.nan)
    return tsi_raw
