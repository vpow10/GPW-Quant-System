from typing import Any

from strategies.base import StrategyBase
from strategies.hybrid_lstm_strategy import HybridLSTMStrategy
from strategies.lstm_strategy import LSTMStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy

# best strategies marked with S/A tier comments, rest honestly garbage
STRATEGY_CONFIG: dict[str, dict[str, Any]] = {
    "momentum": {
        "lookback": 5,
        "entry_long": 0.05,
        "entry_short": -0.05,
        "col_close": "close",
    },
    "lstm": {
        "models_dir": "./models",
        "threshold": 0.003,
        "smoothing_window": 3,
        "exit_threshold": -0.002,
    },
    "hybrid_lstm_10d": {
        "long_only": False,
        "models_dir": "models/hybrid_lstm",
        "z_entry": 1.0,
        "z_exit": 0.3,
        "vol_quantile": 0.7,
        "min_hold_days": 5,
    },
    "mean_reversion": {
        "window": 20,
        "z_entry": 1.5,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    "momentum_tsmom_20d": {
        "lookback": 20,  # ~1 trading month
        "entry_long": 0.0,  # sign of return
        "entry_short": 0.0,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    "momentum_tsmom_60d": {
        "lookback": 60,  # ~3 months
        "entry_long": 0.0,
        "entry_short": 0.0,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    # A tier
    "momentum_tsmom_120d": {
        "lookback": 120,  # ~6 months
        "entry_long": 0.0,
        "entry_short": 0.0,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    "momentum_tsmom_60d_longonly": {
        "lookback": 60,
        "entry_long": 0.0,
        "entry_short": 0.0,
        "col_close": "close",
        "long_only": True,  # only go long on positive momentum, flat otherwise
        "short_only": False,
    },
    "momentum_60d_loose": {
        "lookback": 60,
        "entry_long": 0.03,  # +3% over 60 days (~0.5% per month)
        "entry_short": -0.03,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    # A tier
    "momentum_120d_loose": {
        "lookback": 120,
        "entry_long": 0.05,  # +5% over 6 months (~1.6% per quarter)
        "entry_short": -0.05,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    # S tier
    "momentum_252d_longonly": {
        "lookback": 252,  # ~1 year
        "entry_long": 0.0,
        "entry_short": 0.0,
        "col_close": "close",
        "long_only": True,
        "short_only": False,
    },
    "mean_reversion_20d_longonly": {
        "window": 20,
        "z_entry": 1.5,
        "col_close": "close",
        "long_only": True,  # only buy deep dips
        "short_only": False,
    },
    "mean_reversion_50d_longonly": {
        "window": 50,
        "z_entry": 2.0,  # rarer, bigger dips
        "col_close": "close",
        "long_only": True,
        "short_only": False,
    },
    "mean_reversion_5d_longonly": {
        "window": 5,
        "z_entry": 1.0,  # price 1s below short-term mean
        "col_close": "close",
        "long_only": True,
        "short_only": False,
    },
    "mean_reversion_20d_shortonly": {
        "window": 20,
        "z_entry": 2.0,
        "col_close": "close",
        "long_only": False,
        "short_only": True,
    },
}

STRATEGY_REGISTRY: dict[str, type[StrategyBase]] = {
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "hybrid_lstm_10d": HybridLSTMStrategy,
    "lstm": LSTMStrategy,
    "momentum_tsmom_20d": MomentumStrategy,
    "momentum_tsmom_60d": MomentumStrategy,
    "momentum_tsmom_120d": MomentumStrategy,
    "momentum_60d_loose": MomentumStrategy,
    "momentum_120d_loose": MomentumStrategy,
    "momentum_252d_longonly": MomentumStrategy,
    "mean_reversion_20d_longonly": MeanReversionStrategy,
    "mean_reversion_50d_longonly": MeanReversionStrategy,
    "mean_reversion_5d_longonly": MeanReversionStrategy,
    "mean_reversion_20d_shortonly": MeanReversionStrategy,
}
