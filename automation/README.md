# Automation

This folder contains scripts and configuration for automating the system execution (e.g., via Cron).

## Key Files

- **`run_daily.sh`**: The main entry point for the cron job. It activates the environment, loads configuration, and executes `app.daily_trader`.
- **`daily_config.env`**: Configuration file defining parameters for the daily trader (Strategy, Allocation, etc.).
- **`keep_alive.py`**: A utility script to prevent session timeouts (e.g., refreshing Saxo tokens) if running continuously.
- **`setup_auto.py`**: Helper to configure the automation environment (e.g., generating systemd units or crontab entries).

## Usage Examples

### Manual Run Wrapper
You can test the full automation flow manually:
```bash
./automation/run_daily.sh
```

### Configuration (`daily_config.env`)
Example content:
```env
TRADER_STRATEGY=rsi_14d_basic
TRADER_ALLOCATION=0.2
TRADER_MAX_CAPITAL=100000
TRADER_EXECUTE=true
```
