from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class StrategyBase(ABC):
    """
    Base interface for signal-generating strategies.

    Contract:
        - every strategy MUST implement generate_signals()
        - generate_signals() takes a DataFrame with market data
        - it returns a DataFrame that includes a 'signal' column
          (and optionally additional features)
    """

    name: str = field(init=False)
    params: dict[str, Any] = field(default_factory=dict, init=False)

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Parameters
        ----------
        df:
            DataFrame with OHLCV or other instrument data.

        Returns
        -------
        DataFrame
            Same data with an additional 'signal' column.
        """
        raise NotImplementedError

    def _add_meta(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add generic strategy metadata columns.

        Columns added:
            - 'strategy' : strategy name
            - 'params'   : string representation of strategy parameters
        """
        df = df.copy()
        df["strategy"] = self.name
        df["params"] = str(self.params)
        return df
