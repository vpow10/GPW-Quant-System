from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class StrategyBase(ABC):

    """
    Bazowy interfejs dla strategii generujących sygnały na podstawie danych OHLCV.

    Kontrakt:
      - każda strategia MUSI zaimplementować generate_signals()
      - generate_signals() bierze df z danymi rynkowymi
      - zwraca df z kolumną 'signal' (+ ewentualnie dodatkowymi feature'ami)
    """

    name: str = field(init=False)
    params: dict[str, Any] = field(default_factory=dict, init=False)

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Wejście:
          df: DataFrame z kolumnami z cenami instrumentu finansowego
        Wyjście:
          df z dodatkową kolumną 'signal'
        """
        raise NotImplementedError

    def _add_meta(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["strategy"] = self.name
        df["params"] = str(self.params)
        return df
