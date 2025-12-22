"""
Module to sync GPW stock data from Saxo OpenApi to data/raw/*.csv.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from data.scripts.saxo_auth import ensure_access_token

load_dotenv()

DATA_DIR = Path("data/raw")
OPENAPI_BASE = (
    os.getenv("SAXO_OPENAPI_BASE") or "https://gateway.saxobank.com/sim/openapi"
).rstrip("/")

# Mapping: UIC -> Filename
UIC_MAP = {
    32368: "acp.csv",
    45348: "bhw.csv",
    25272: "peo.csv",
    53862: "brs.csv",
    25277: "gtc.csv",
    53764: "jsw.csv",
    45368: "ker.csv",
    25285: "kgh.csv",
    45371: "lwb.csv",
    46127: "pge.csv",
    25275: "pkn.csv",
    25279: "pko.csv",
    47019: "pzu.csv",
    48752: "tpe.csv",
}

NAME_MAP = {
    32368: "Asseco",
    45348: "Citi Handlowy",
    25272: "Pekao",
    53862: "Boryszew",
    25277: "GTC",
    53764: "JSW",
    45368: "Kernel",
    25285: "KGHM",
    45371: "Bogdanka",
    46127: "PGE",
    25275: "PKN Orlen",
    25279: "PKO BP",
    47019: "PZU",
    48752: "Tauron",
}


def get_last_date(filepath: Path) -> str | None:
    if not filepath.exists():
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return None
            last_date = None
            for row in reader:
                if row:
                    last_date = row[0]
            return last_date
    except Exception:
        return None


def fetch_ohlc(uic: int, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch daily OHLCV data from Saxo."""
    token = ensure_access_token()
    url = f"{OPENAPI_BASE}/chart/v3/charts"

    params: dict[str, str | int] = {
        "Uic": uic,
        "AssetType": "Stock",
        "Horizon": 1440,
        "Count": limit,
        "FieldGroups": "Data",
    }

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with httpx.Client(timeout=30) as client:
        r = client.get(url, params=params, headers=headers)
        if r.status_code != 200:
            print(f"Error fetching data for UIC {uic}: {r.status_code} {r.text}")
            return []

        data = r.json()
        return data.get("Data", [])


def fetch_intraday_ohlc(uic: int, horizon: int = 60, limit: int = 200) -> list[dict[str, Any]]:
    """Fetch intraday OHLC data from Saxo (e.g. 60-minute bars)."""
    token = ensure_access_token()
    url = f"{OPENAPI_BASE}/chart/v3/charts"

    params: dict[str, str | int] = {
        "Uic": uic,
        "AssetType": "Stock",
        "Horizon": horizon,  # minutes; 60 = hourly
        "Count": limit,  # number of bars back
        "FieldGroups": "Data",
    }

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with httpx.Client(timeout=30) as client:
        r = client.get(url, params=params, headers=headers)
        if r.status_code != 200:
            print(f"Error fetching intraday data for UIC {uic}: {r.status_code} {r.text}")
            return []

        data = r.json()
        return data.get("Data", [])


def parse_saxo_time(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d")


def append_data(filepath: Path, new_rows: list[dict[str, Any]]) -> int:
    if not new_rows:
        return 0
    count = 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in new_rows:
            date_str = parse_saxo_time(row["Time"])
            line = [
                date_str,
                row["Open"],
                row["High"],
                row["Low"],
                row["Close"],
                int(row.get("Volume", 0)),
            ]
            writer.writerow(line)
            count += 1
    return count


def sync_gpw_data() -> list[str]:
    """
    Syncs data for all configured GPW instruments.
    Returns a list of log messages describing what happened.
    """
    logs = []
    logs.append(f"Starting sync for {len(UIC_MAP)} instruments...")

    for uic, filename in UIC_MAP.items():
        name = NAME_MAP.get(uic, str(uic))
        filepath = DATA_DIR / filename

        last_date = get_last_date(filepath)
        if not last_date:
            logs.append(f"[{name}] No local file/date. Skipping.")
            continue

        raw_data = fetch_ohlc(uic, limit=100)
        new_data = []
        for row in raw_data:
            if parse_saxo_time(row["Time"]) > last_date:
                new_data.append(row)

        if new_data:
            c = append_data(filepath, new_data)
            logs.append(f"[{name}] +{c} rows (to {parse_saxo_time(new_data[-1]['Time'])})")
        else:
            # logs.append(f"[{name}] Up to date.")
            pass

    return logs
