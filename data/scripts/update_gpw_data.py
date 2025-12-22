"""
Script to update GPW stock data in data/raw/*.csv using Saxo OpenApi.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from .saxo_auth import ensure_access_token

load_dotenv()

# --- Configuration ---

DATA_DIR = Path("data/raw")
OPENAPI_BASE = (
    os.getenv("SAXO_OPENAPI_BASE") or "https://gateway.saxobank.com/sim/openapi"
).rstrip("/")

# Mapping: UIC -> Filename (basename in data/raw)
# Based on user request and existing file structure.
UIC_MAP = {
    32368: "acp.csv",  # Asseco Poland SA
    45348: "bhw.csv",  # Bank Handlowy w Warszawie SA
    25272: "peo.csv",  # Bank Polska Kasa Opieki SA (PEO / Pekao)
    53862: "brs.csv",  # Boryszew SA
    25277: "gtc.csv",  # Globe Trade Centre SA
    53764: "jsw.csv",  # Jastrzebska Spolka Weglowa SA
    45368: "ker.csv",  # Kernel Holding SA
    25285: "kgh.csv",  # KGHM Polska Miedz SA
    45371: "lwb.csv",  # LW Bogdanka SA
    46127: "pge.csv",  # PGE Polska Grupa Energetyczna SA
    25275: "pkn.csv",  # ORLEN Spolka Akcyjna (formerly PKN Orlen)
    25279: "pko.csv",  # Powszechna Kasa Oszczednosci Bank Polski SA
    47019: "pzu.csv",  # Powszechny Zaklad Ubezpieczen SA
    48752: "tpe.csv",  # Tauron Polska Energia SA
}

NAME_MAP = {
    32368: "Asseco Poland",
    45348: "Bank Handlowy",
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

# --- Helpers ---


def get_last_date(filepath: Path) -> str | None:
    """Read the last date from the CSV file (YYYY-MM-DD)."""
    if not filepath.exists():
        return None

    last_date = None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return None
            for row in reader:
                if row:
                    last_date = row[0]  # Assuming first column is Data/Date
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}")
        return None
    return last_date


def fetch_ohlc(uic: int, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch daily OHLCV data from Saxo."""
    token = ensure_access_token()
    url = f"{OPENAPI_BASE}/chart/v3/charts"

    params: dict[str, str | int] = {
        "Uic": uic,
        "AssetType": "Stock",
        "Horizon": 1440,  # Daily
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


def parse_saxo_time(ts: str) -> str:
    """Convert Saxo time (ISO 8601) to YYYY-MM-DD."""
    # Example: 2023-10-27T00:00:00.000000Z
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d")


def append_data(filepath: Path, new_rows: list[dict[str, Any]]) -> int:
    """Append new rows to the CSV file via simple write."""
    if not new_rows:
        return 0

    # Format: Data,Otwarcie,Najwyzszy,Najnizszy,Zamkniecie,Wolumen

    count = 0
    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in new_rows:
            date_str = parse_saxo_time(row["Time"])
            # Saxo gives: Open, High, Low, Close, Volume
            # CSV expects: Data, Otwarcie, Najwyzszy, Najnizszy, Zamkniecie, Wolumen

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


# --- Main ---


def main() -> None:
    print(f"Starting update for {len(UIC_MAP)} instruments...")

    for uic, filename in UIC_MAP.items():
        name = NAME_MAP.get(uic, str(uic))
        filepath = DATA_DIR / filename

        if not filepath.exists():
            print(f"[{name}] File not found: {filepath}. Skipping.")
            continue

        last_date = get_last_date(filepath)
        if not last_date:
            print(f"[{name}] Could not determine last date. Skipping.")
            continue

        # Fetch data
        # We fetch e.g. last 100 days to be safe and overlap
        print(f"[{name}] Last date: {last_date}. Fetching recent data...")
        raw_data = fetch_ohlc(uic, limit=100)

        if not raw_data:
            print(f"[{name}] No data returned from API.")
            continue

        # Filter new data
        new_data = []
        for row in raw_data:
            row_date = parse_saxo_time(row["Time"])
            if row_date > last_date:
                new_data.append(row)

        if new_data:
            count = append_data(filepath, new_data)
            print(
                f"[{name}] Appended {count} new rows. Newest: {parse_saxo_time(new_data[-1]['Time'])}"
            )
        else:
            print(f"[{name}] Up to date.")

    print("\nUpdate complete.")


if __name__ == "__main__":
    main()
