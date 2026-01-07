# App

This directory contains the main application logic, including the Web Dashboard and the Execution Engine.

## Key Files

- **`web.py`**: Flask web application server. Serves the Dashboard UI and API endpoints.
- **`daily_trader.py`**: The primary script for Live/Paper trading. It fetches data, generates signals, calculates target positions, and executes trades via the Saxo API.
- **`engine.py`**: Business logic layer bridging the Saxo Client and Strategy logic.
- **`intraday_trader.py`**: (Experimental) Logic for intraday trading operations.

## Usage Examples

### Running the Web Dashboard
```bash
# Starts the web server on http://localhost:5000
python -m app.web
```

### Running the Daily Trader
This is typically run via `automation/run_daily.sh` (Cron), but can be run manually:

```bash
# Dry Run (no real orders)
python -m app.daily_trader --strategy rsi_14d_basic --allocation-pct 0.1

# Real Execution (DANGER: Places orders)
python -m app.daily_trader --strategy rsi_14d_basic --allocation-pct 0.1 --execute
```

### Environment Variables
Ensure `.env` contains:
- `SAXO_URL`, `SAXO_APP_KEY`, `SAXO_APP_SECRET` (for trading)
- `FLASK_APP=app.web` (for flask commands)
