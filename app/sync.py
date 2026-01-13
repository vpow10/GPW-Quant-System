"""
Module to sync GPW stock data from Stooq (incremental) and run the full pipeline.
Replaces the old Saxo-based sync.
"""
from __future__ import annotations

import csv
import sys
import subprocess
import os
from datetime import datetime, timedelta, date
from pathlib import Path
from io import BytesIO
from typing import Any, cast

import pandas as pd
import httpx
from dotenv import load_dotenv

from data.scripts.saxo_auth import ensure_access_token

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from data.scripts import stooq_fetch
from data.scripts import preprocess_gpw

load_dotenv()

DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"
PYTHON_EXE = sys.executable

OPENAPI_BASE = (
    os.getenv("SAXO_OPENAPI_BASE") or "https://gateway.saxobank.com/sim/openapi"
).rstrip("/")

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

def fetch_intraday_ohlc(uic: int, horizon: int = 60, limit: int = 200) -> list[dict[str, Any]]:
    """Fetch intraday OHLC data from Saxo (e.g. 60-minute bars)."""
    token = ensure_access_token()
    url = f"{OPENAPI_BASE}/chart/v3/charts"

    params: dict[str, str | int] = {
        "Uic": uic,
        "AssetType": "Stock",
        "Horizon": horizon, 
        "Count": limit,
        "FieldGroups": "Data",
    }

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    with httpx.Client(timeout=30) as client:
        r = client.get(url, params=params, headers=headers)
        if r.status_code != 200:
            print(f"Error fetching intraday data for UIC {uic}: {r.status_code} {r.text}")
            return []

        data = r.json()
        return cast("list[dict[str, Any]]", data.get("Data", []))

def get_last_date(filepath: Path) -> date | None:
    """Read the last date from a Stooq-format CSV (Data, Otwarcie, ...)."""
    if not filepath.exists():
        return None
    try:
        df = pd.read_csv(filepath, usecols=["Data"])
        if df.empty:
            return None
        last_str = df["Data"].iloc[-1]
        return datetime.strptime(last_str, "%Y-%m-%d").date()
    except Exception as e:
        print(f"Warning: Could not read date from {filepath}: {e}")
        return None

def merge_and_save(filepath: Path, new_content: bytes) -> int:
    """
    Merge new CSV bytes with existing file. 
    Returns number of new rows added (approx).
    """
    try:
        new_df = pd.read_csv(BytesIO(new_content))
    except Exception as e:
        print(f"  [Error] Failed to parse fetched CSV: {e}")
        return 0

    if new_df.empty:
        return 0

    if filepath.exists():
        try:
            old_df = pd.read_csv(filepath)
            combined = pd.concat([old_df, new_df])
            combined = combined.drop_duplicates(subset=["Data"], keep="last")
            combined = combined.sort_values("Data")
        except Exception as e:
            print(f"  [Error] Failed to merge with existing file: {e}. Overwriting.")
            combined = new_df
    else:
        combined = new_df

    combined.to_csv(filepath, index=False)
    return len(new_df)

def sync_stooq_smart() -> tuple[list[str], int]:
    """
    1. Read list of selected symbols.
    2. Check local files for last date.
    3. Fetch incremental data.
    4. Merge.
    Returns: (list of log messages, updated_count)
    """
    logs = []
    logs.append("--- Starting Smart Stooq Sync ---")
    
    try:
        names = stooq_fetch.read_gpw_selected_names()
        mapping = stooq_fetch.names_to_symbols(names)
        mapping["WIG20 Index"] = "wig20"
    except Exception as e:
        logs.append(f"[ERROR] Failed to read selected names: {e}")
        return logs, 0

    updated_count = 0
    
    for name, symbol in mapping.items():
        filepath = DATA_RAW / f"{symbol.lower()}.csv"
        
        last_date = get_last_date(filepath)
        start_date = None
        if last_date:
            start_date = last_date + timedelta(days=1)
            if start_date > date.today():
                logs.append(f"[SKIP] {name} ({symbol}): Up to date ({last_date})")
                continue
            logs.append(f"[UPDATE] {name} ({symbol}): Fetching from {start_date}...")
        else:
            logs.append(f"[INIT] {name} ({symbol}): Fetching full history...")
            start_date = date(2000, 1, 1)

        try:
            payload = stooq_fetch.fetch_csv(symbol, start=start_date)
            rows_added = merge_and_save(filepath, payload)
            if rows_added > 0:
                logs.append(f"       -> Added {rows_added} rows.")
                updated_count += 1
            else:
                logs.append("       -> No new data.")
                
        except Exception as e:
            logs.append(f"       -> [FAIL] {e}")

    logs.append(f"--- Sync Complete. Updated {updated_count} files. ---")
    return logs, updated_count

def run_pipeline() -> None:
    """
    Run the subsequent pipeline steps (cli mode, can exit).
    """
    try:
        run_pipeline_safe()
    except Exception as e:
        print(f"Pipeline failed: {e}")
        sys.exit(1)

def run_pipeline_safe() -> None:
    """
    Run pipeline without sys.exit, suitable for web calls.
    """
    print("\n--- Running Preprocessing ---")
    preprocess_gpw.cmd_all()

    print("\n--- Running Strategies ---")
    cmd = [
        PYTHON_EXE,
        "-m",
        "strategies.run_strategies",
        "--strategies", "all",
        "--input", str(DATA_PROCESSED / "reports" / "combined.parquet"),
        "--output-dir", str(REPO_ROOT / "data" / "signals"),
    ]
    print(f"Command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

def sync_gpw_data() -> list[str]:
    logs, count = sync_stooq_smart()
    
    if count == 0:
        logs.append("--- No updates found. Skipping pipeline. ---")
        return logs

    try:
        logs.append("--- Triggering Pipeline ---")
        run_pipeline_safe()
        logs.append("Pipeline executed successfully.")
    except Exception as e:
        logs.append(f"Pipeline failed: {e}")
    return logs

def main():
    logs, count = sync_stooq_smart()
    for l in logs:
        print(l)
    
    if count > 0:
        run_pipeline()
    else:
        print("--- No updates found. Skipping pipeline. ---")

if __name__ == "__main__":
    main()
