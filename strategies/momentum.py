from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from strategies.base import StrategyBase


@dataclass
class MomentumStrategy(StrategyBase):
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
            raise ValueError(f"MeanReversionStrategy: missing columns: {missing}")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Wejście:
        df: DataFrame z kolumnami:
            - 'symbol'
            - 'date'
            - col_close (domyślnie 'close')

        signal:
            +1 → sygnał LONG (kupno / zajęcie pozycji długiej)
            0 → brak pozycji (neutralnie; momentum zbyt słabe)
            -1 → sygnał SHORT (sprzedaż / zajęcie pozycji krótkiej)

        Pozostałe kolumny:
            - 'momentum' : miara siły trendu (close_t / close_{t-lookback} - 1)
            - 'strategy' : nazwa strategii
            - 'params'   : parametry strategii w formie tekstowej
        """

        self._validate_input(df)

        df = df.sort_values(["symbol", "date"]).copy()
        df["momentum"] = df.groupby("symbol")[self.col_close].transform(
            lambda s: s / s.shift(self.lookback) - 1.0
        )

        df["signal"] = 0
        df.loc[df["momentum"] > self.entry_long, "signal"] = 1
        df.loc[df["momentum"] < self.entry_short, "signal"] = -1

        return self._add_meta(df)
