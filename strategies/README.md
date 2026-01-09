# Strategies

This folder contains the core trading logic implementations and signal generation scripts.
All strategies inherit from `base.StrategyBase`.

## Key Files

- **`config_strategies.py`**: Registry of all available strategies and their parameter configurations.
- **`run_strategies.py`**: Script to generate signal files (Parquet/CSV) from market data using defined strategies.
- **`rsi.py`**: Relative Strength Index (RSI) mean reversion strategy.
- **`momentum.py`**: Time Series Momentum (Trend Following) strategy.
- **`mean_reversion.py`**: Z-Score based mean reversion strategy.
- **`lstm_strategy.py`** & **`hybrid_lstm_strategy.py`**: Neural Network based strategies.

## Usage Examples

### Generating Signals
To generate signals for a specific strategy (e.g., `rsi_14d_basic`) using the combined market data:

```bash
# From project root
python -m strategies.run_strategies \
    --strategies rsi_14d_basic \
    --input data/processed/reports/combined.parquet \
    --output-dir data/signals
```

### Adding a New Strategy
1. Create a new file (e.g., `my_strategy.py`) inheriting from `StrategyBase`.
2. Implement `generate_signals(df)`.
3. Register the class and config in `config_strategies.py`.
