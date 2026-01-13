from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from strategies.base import StrategyBase


@dataclass
class MomentumStrategy(StrategyBase):
    """
    Simple time-series momentum / trend-following strategy.

    Idea:
        - look at the return over the last `lookback` bars
        - if the return is strongly positive -> go LONG
        - if the return is strongly negative -> go SHORT
        - otherwise stay FLAT

    Parameters
    ----------
    lookback:
        Lookback window (in days/bars) used to compute momentum.
    entry_long:
        Threshold for going long; if momentum > entry_long -> LONG.
    entry_short:
        Threshold for going short; if momentum < entry_short -> SHORT.
    col_close:
        Column name for the closing price.
    long_only:
        If True, the strategy generates only LONG signals (1 or 0).
    short_only:
        If True, the strategy generates only SHORT signals (-1 or 0).

    Signals
    -------
    signal =  1  -> LONG
    signal =  0  -> FLAT
    signal = -1  -> SHORT

    Feature columns
    ---------------
    momentum:
        (close_t / close_{t-lookback}) - 1
    """

    lookback: int = 5
    entry_long: float = 0.05
    entry_short: float = -0.05
    col_close: str = "close"
    long_only: bool = False
    short_only: bool = False

    def __post_init__(self):
        self.name = "MomentumStrategy"
        self.params = {
            "lookback": self.lookback,
            "entry_long": self.entry_long,
            "entry_short": self.entry_short,
            "col_close": self.col_close,
            "long_only": self.long_only,
            "short_only": self.short_only,
        }

    def _validate_input(self, df: pd.DataFrame) -> None:
        required = {"symbol", "date", self.col_close}
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"MomentumStrategy: missing columns: {missing}")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generate momentum signals for each symbol.

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
                - 'momentum' : time-series momentum
                - 'signal'   : -1 / 0 / +1
                - 'strategy' : strategy name
                - 'params'   : parameters as string
        """

        self._validate_input(df)

        df = df.sort_values(["symbol", "date"]).copy()
        df["momentum"] = df.groupby("symbol")[self.col_close].transform(
            lambda s: s / s.shift(self.lookback) - 1.0
        )

        df["signal"] = 0
        if not self.short_only:
            df.loc[df["momentum"] > self.entry_long, "signal"] = 1

        if not self.long_only:
            df.loc[df["momentum"] < self.entry_short, "signal"] = -1

        return self._add_meta(df)
