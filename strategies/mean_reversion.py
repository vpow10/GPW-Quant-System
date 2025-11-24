from __future__ import annotations

from dataclasses import dataclass
from typing import Set

import pandas as pd

from strategies.base import StrategyBase


@dataclass
class MeanReversionStrategy(StrategyBase):
    """
    Simple moving-average mean-reversion strategy.

    Idea:
        - if price is FAR below its moving average → go LONG
        - if price is FAR above its moving average → go SHORT

    Parameters
    ----------
    window:
        Rolling window length (in days/bars) used to compute the mean and std.
    z_entry:
        How many standard deviations away from the mean we consider "far".
    col_close:
        Column name for the closing price.
    long_only:
        If True, the strategy generates only LONG signals (1 or 0).
    short_only:
        If True, the strategy generates only SHORT signals (-1 or 0).

    Signals
    -------
    signal =  1  → LONG  - price significantly below the moving average
    signal =  0  → FLAT  - no position
    signal = -1  → SHORT - price significantly above the moving average
    """

    window: int = 20
    z_entry: float = 1.5
    col_close: str = "close"
    long_only: bool = False
    short_only: bool = False

    def __post_init__(self) -> None:
        self.name = "MeanReversionStrategy"
        self.params = {
            "window": self.window,
            "z_entry": self.z_entry,
            "col_close": self.col_close,
            "long_only": self.long_only,
            "short_only": self.short_only,
        }

    def _validate_input(self, df: pd.DataFrame) -> None:
        required: Set[str] = {"date", "symbol"}

        missing = [c for c in required if c not in df.columns]
        if self.col_close not in df.columns:
            missing.append(self.col_close)

        if missing:
            raise ValueError(f"MeanReversionStrategy: missing columns: {missing}")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Parameters
        ----------
        df:
            DataFrame with columns:
                - 'symbol'
                - 'date'
                - col_close (default: 'close')

        Returns
        -------
        DataFrame
            Original data plus:
                - 'ma'      : rolling mean over `window`
                - 'std'     : rolling standard deviation over `window`
                - 'zscore'  : (close - ma) / std
                - 'signal'  : -1 / 0 / +1
                - 'strategy': strategy name
                - 'params'  : strategy parameters as string
        """

        self._validate_input(df)

        df = df.sort_values(["symbol", "date"]).copy()

        g = df.groupby("symbol")[self.col_close]
        df["ma"] = g.transform(lambda s: s.rolling(self.window, min_periods=self.window).mean())
        df["std"] = g.transform(
            lambda s: s.rolling(self.window, min_periods=self.window).std(ddof=0)
        )

        df["zscore"] = (df[self.col_close] - df["ma"]) / df["std"]

        df["signal"] = 0

        if not self.short_only:
            df.loc[df["zscore"] < -self.z_entry, "signal"] = 1

        if not self.long_only:
            df.loc[df["zscore"] > self.z_entry, "signal"] = -1

        return self._add_meta(df)
