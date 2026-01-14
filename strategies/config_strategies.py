from __future__ import annotations

from importlib import import_module
from typing import Any, Callable

from strategies.base import StrategyBase
from strategies.mean_reversion import MeanReversionStrategy
from strategies.momentum import MomentumStrategy
from strategies.rsi import RSIStrategy

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
    "mean_reversion": {
        "window": 20,
        "z_entry": 1.5,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    "hybrid_lstm_10d": {
        "long_only": False,
        "models_dir": "models/hybrid_lstm",
        "z_entry": 1.0,
        "z_exit": 0.3,
        "vol_quantile": 0.7,
        "min_hold_days": 5,
    },
    "momentum_tsmom_20d": {
        "lookback": 20,
        "entry_long": 0.0,
        "entry_short": 0.0,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    "rsi_14d_basic": {
        "period": 14,
        "lower_bound": 30.0,
        "upper_bound": 70.0,
        "col_close": "close",
        "long_only": False,
    },
    "rsi_14d_longonly": {
        "period": 14,
        "lower_bound": 30.0,
        "upper_bound": 70.0,
        "col_close": "close",
        "long_only": True,
    },
    "rsi_7d": {
        "period": 7,
        "lower_bound": 30.0,
        "upper_bound": 70.0,
        "col_close": "close",
        "long_only": False,
    },
    "rsi_7d_longonly": {
        "period": 7,
        "lower_bound": 30.0,
        "upper_bound": 70.0,
        "col_close": "close",
        "long_only": True,
    },
    "rsi_30d": {
        "period": 30,
        "lower_bound": 30.0,
        "upper_bound": 70.0,
        "col_close": "close",
        "long_only": False,
    },
    "rsi_30d_longonly": {
        "period": 30,
        "lower_bound": 30.0,
        "upper_bound": 70.0,
        "col_close": "close",
        "long_only": True,
    },
    "momentum_tsmom_60d": {
        "lookback": 60,
        "entry_long": 0.0,
        "entry_short": 0.0,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    # A tier
    "momentum_tsmom_120d": {
        "lookback": 120,
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
        "long_only": True,
        "short_only": False,
    },
    "momentum_60d_loose": {
        "lookback": 60,
        "entry_long": 0.03,
        "entry_short": -0.03,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    # A tier
    "momentum_120d_loose": {
        "lookback": 120,
        "entry_long": 0.05,
        "entry_short": -0.05,
        "col_close": "close",
        "long_only": False,
        "short_only": False,
    },
    # S tier
    "momentum_252d_longonly": {
        "lookback": 252,
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
        "long_only": True,
        "short_only": False,
    },
    "mean_reversion_50d_longonly": {
        "window": 50,
        "z_entry": 2.0,
        "col_close": "close",
        "long_only": True,
        "short_only": False,
    },
    "mean_reversion_5d_longonly": {
        "window": 5,
        "z_entry": 1.0,
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

# Non-ML strategies registered eagerly (safe)
STRATEGY_REGISTRY: dict[str, type[StrategyBase]] = {
    "momentum": MomentumStrategy,
    "mean_reversion": MeanReversionStrategy,
    "momentum_tsmom_20d": MomentumStrategy,
    "momentum_tsmom_60d": MomentumStrategy,
    "momentum_tsmom_120d": MomentumStrategy,
    "momentum_tsmom_60d_longonly": MomentumStrategy,
    "momentum_60d_loose": MomentumStrategy,
    "momentum_120d_loose": MomentumStrategy,
    "momentum_252d_longonly": MomentumStrategy,
    "mean_reversion_20d_longonly": MeanReversionStrategy,
    "mean_reversion_50d_longonly": MeanReversionStrategy,
    "mean_reversion_5d_longonly": MeanReversionStrategy,
    "mean_reversion_20d_shortonly": MeanReversionStrategy,
    "rsi_14d_basic": RSIStrategy,
    "rsi_14d_longonly": RSIStrategy,
    "rsi_7d": RSIStrategy,
    "rsi_7d_longonly": RSIStrategy,
    "rsi_30d": RSIStrategy,
    "rsi_30d_longonly": RSIStrategy,
}

# ML strategies registered lazily (import torch only if requested)
_LAZY_REGISTRY: dict[str, Callable[[], type[StrategyBase]]] = {
    "lstm": lambda: _import_cls("strategies.lstm_strategy", "LSTMStrategy"),
    "hybrid_lstm_10d": lambda: _import_cls(
        "strategies.hybrid_lstm_strategy", "HybridLSTMRegimeBlendStrategy"
    ),
}


def _import_cls(module_path: str, class_name: str) -> type[StrategyBase]:
    mod = import_module(module_path)
    cls = getattr(mod, class_name)
    if not isinstance(cls, type) or not issubclass(cls, StrategyBase):
        raise TypeError(f"{module_path}.{class_name} is not a StrategyBase subclass")
    return cls


def get_strategy_class(strategy_name: str) -> type[StrategyBase]:
    """
    Fetch strategy class by name.
    Imports optional ML strategy modules only when needed.
    """
    if strategy_name in STRATEGY_REGISTRY:
        return STRATEGY_REGISTRY[strategy_name]

    if strategy_name in _LAZY_REGISTRY:
        cls = _LAZY_REGISTRY[strategy_name]()
        STRATEGY_REGISTRY[strategy_name] = cls
        return cls

    raise KeyError(f"Unknown strategy: {strategy_name}")
