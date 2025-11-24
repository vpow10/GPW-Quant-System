from typing import Any

from strategies.base import StrategyBase
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy

STRATEGY_CONFIG: dict[str, dict[str, Any]] = {
    "momentum": {
        "lookback": 5,
        "entry_long": 0.05,
        "entry_short": -0.05,
        "col_close": "close",
    },
    "mean_reversion": {
        "window": 20,
        "z_entry": 1.5,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
}

STRATEGY_REGISTRY: dict[str, type[StrategyBase]] = {
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
}
