"""
RSI Mean Reversion Strategy.
"""


import numpy as np
import pandas as pd

from strategies.base import StrategyBase


class RSIStrategy(StrategyBase):
    """
    Basic RSI Mean Reversion Strategy.

    Logic:
    - RSI < lower_bound (e.g. 30) -> BUY (Oversold)
    - RSI > upper_bound (e.g. 70) -> SELL (Overbought)
    """

    def __init__(
        self,
        period: int = 14,
        lower_bound: float = 30.0,
        upper_bound: float = 70.0,
        col_close: str = "close",
        long_only: bool = False,
        exit_long_level: float = 50.0,
        exit_short_level: float = 50.0,
    ):
        self.period = period
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.col_close = col_close
        self.long_only = long_only
        self.exit_long_level = exit_long_level
        self.exit_short_level = exit_short_level

        self.params = {
            "period": period,
            "lower_bound": lower_bound,
            "upper_bound": upper_bound,
            "long_only": long_only,
            "exit_long_level": exit_long_level,
            "exit_short_level": exit_short_level,
        }

    def _calc_rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).fillna(0)
        loss = (-delta.where(delta < 0, 0)).fillna(0)

        avg_gain = gain.rolling(window=period, min_periods=period).mean()
        avg_loss = loss.rolling(window=period, min_periods=period).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        if self.col_close not in df.columns:
            df["signal"] = 0
            return df

        close = df[self.col_close]

        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        # Wilder's Smoothing (alpha=1/period)
        avg_gain = gain.ewm(alpha=1 / self.period, min_periods=self.period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self.period, min_periods=self.period, adjust=False).mean()

        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))

        rsi_vals = df["rsi"].to_numpy()

        sig_arr = np.zeros(len(df))

        curr_sig = 0
        for i in range(self.period, len(df)):
            val = rsi_vals[i]

            if np.isnan(val):
                continue

            if val < self.lower_bound:
                curr_sig = 1
            elif val > self.upper_bound:
                if self.long_only:
                    curr_sig = 0  # Exit long
                else:
                    curr_sig = -1  # Go short
            else:
                if curr_sig == 1 and val > self.exit_long_level:
                    curr_sig = 0

                if curr_sig == -1 and val < self.exit_short_level:
                    curr_sig = 0

                pass

            sig_arr[i] = curr_sig

        df["signal"] = sig_arr
        return df
