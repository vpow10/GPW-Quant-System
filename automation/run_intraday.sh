#!/bin/bash
# Wrapper to run Intraday Trader from cron (e.g. every hour)

cd "$(dirname "$0")/.."

source .venv/bin/activate
source .env

CONFIG_FILE="automation/intraday_config.env"
if [ -f "$CONFIG_FILE" ]; then
    set -a
    source "$CONFIG_FILE"
    set +a
else
    echo "Config file not found: $CONFIG_FILE"
    exit 1
fi

STRATEGY="${TRADER_STRATEGY:-hybrid_lstm_10d}"
ALLOC="${TRADER_ALLOCATION:-0.2}"
LONG_ONLY="${TRADER_LONG_ONLY:-false}"
EXEC="${TRADER_EXECUTE:-false}"
MAX_CAP="${TRADER_MAX_CAPITAL:-500000}"
DAILY_SPEND="${TRADER_MAX_DAILY_SPEND:-100000}"
FX_RATE="${TRADER_FX_RATE:-4.0}"

FLAGS="--strategy $STRATEGY --allocation-pct $ALLOC --auto-allocate"
FLAGS="$FLAGS --max-capital $MAX_CAP --max-daily-spend $DAILY_SPEND --fx-rate $FX_RATE"
FLAGS="$FLAGS --horizon-min 60 --lookback-bars 200"

if [ "$LONG_ONLY" = "true" ]; then
    FLAGS="$FLAGS --long-only"
fi

if [ "$EXEC" = "true" ]; then
    FLAGS="$FLAGS --execute"
fi

echo "[$(date)] Running Intraday Trader..."
python -m app.intraday_trader $FLAGS >> automation/intraday.log 2>&1
echo "[$(date)] Done."
