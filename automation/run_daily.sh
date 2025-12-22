#!/bin/bash
# Wrapper to run Daily Trader from cron

# 0. Navigate to Project Root (adjust if needed)
cd "$(dirname "$0")/.."

# 1. Load Environment
source .venv/bin/activate
source .env

# 2. Load Config
CONFIG_FILE="automation/daily_config.env"
if [ -f "$CONFIG_FILE" ]; then
    set -a
    source "$CONFIG_FILE"
    set +a
else
    echo "Config file not found: $CONFIG_FILE"
    exit 1
fi

# 3. Construct Flags
FLAGS="--strategy $TRADER_STRATEGY --allocation-pct $TRADER_ALLOCATION --auto-allocate"

# Defaults if not set in env
: "${TRADER_MAX_CAPITAL:=500000}"
: "${TRADER_MAX_DAILY_SPEND:=50000}"
: "${TRADER_FX_RATE:=4.0}"

FLAGS="$FLAGS --max-capital $TRADER_MAX_CAPITAL --max-daily-spend $TRADER_MAX_DAILY_SPEND --fx-rate $TRADER_FX_RATE"

if [ "$TRADER_LONG_ONLY" = "true" ]; then
    FLAGS="$FLAGS --long-only"
fi

if [ "$TRADER_EXECUTE" = "true" ]; then
    FLAGS="$FLAGS --execute"
fi

# 4. Run
echo "[$(date)] Running Daily Trader..."
python -m app.daily_trader $FLAGS >> automation/daily.log 2>&1
echo "[$(date)] Done."
