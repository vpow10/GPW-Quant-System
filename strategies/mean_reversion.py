# gpw_quant/strategies/mean_reversion.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Set

import pandas as pd

from strategies.base import StrategyBase


@dataclass
class MeanReversionStrategy(StrategyBase):
    """
    Strategia mean reversion (powrót do średniej).

    Idea:
      - jeśli cena jest DUŻO poniżej średniej → kup (LONG), liczymy na odbicie
      - jeśli cena jest DUŻO powyżej średniej → sprzedaj / shortuj (SHORT), liczymy na korektę

    Parametry:
      window     : długość okna do liczenia średniej i odchylenia (w dniach / świecach)
      z_entry    : ile odchyleń standardowych od średniej uznajemy za "dużo"
      col_close  : nazwa kolumny z ceną zamknięcia
      long_only  : jeśli True, strategia generuje TYLKO sygnały LONG (1 lub 0)
      short_only : jeśli True, strategia generuje TYLKO sygnały SHORT (-1 lub 0)

    Sygnały:
      signal =  1  → kup (LONG) – cena znacznie poniżej średniej (zscore < -z_entry)
      signal =  0  → brak pozycji / neutralnie
      signal = -1  → sprzedaj / short (SHORT) – cena znacznie powyżej średniej (zscore > z_entry)
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
        Wejście:
          df: DataFrame z kolumnami:
            - 'symbol'
            - 'date'
            - col_close (domyślnie 'close')

        Wyjście:
          df z dodatkowymi kolumnami:
              - 'ma'      : średnia krocząca z 'window' okresów
              - 'std'     : odchylenie standardowe z 'window' okresów
              - 'zscore'  : (close - ma) / std
              - 'signal'  : -1 / 0 / +1  (SHORT / brak / LONG)
              - 'strategy': nazwa strategii
              - 'params'  : parametry strategii (string)
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
