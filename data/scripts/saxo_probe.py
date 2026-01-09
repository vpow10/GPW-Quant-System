# ruff: noqa T201
"""Minimal probe script to get some data from Saxo OpenAPI.
Example uses:
- saxo_probe.py instruments --keywords PKN --asset-type Stock
- saxo_probe.py instruments --keywords EURUSD --asset-type FxSpot
- saxo_probe.py chart --uic 25275 --asset-type Stock --horizon 1440 --count 50
- saxo_probe.py chart --uic 21 --asset-type FxSpot --horizon 60 --count 120
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx
from dotenv import load_dotenv

from .saxo_auth import ensure_access_token

load_dotenv()

OPENAPI_BASE = os.getenv("SAXO_OPENAPI_BASE")
TOKEN = os.getenv("SAXO_TOKEN")


def _require_token() -> str:
    """Checks if API TOKEN is given in .env file."""
    if not TOKEN:
        print("SAXO_TOKEN missing. Put your 24-hour token in .env (SAXO_TOKEN=...).")
        sys.exit(1)
    return TOKEN


def api_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Minimal GET wrapper with useful error text."""
    token = ensure_access_token()
    url = f"{OPENAPI_BASE}{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    with httpx.Client(timeout=30) as client:
        r = client.get(url, params=params or {}, headers=headers)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail: str
            try:
                detail = r.json()  # type: ignore[assignment]
            except Exception:
                detail = r.text
            raise SystemExit(f"HTTP {r.status_code} for {url} -> {detail}") from e
        return r.json()  # type: ignore[return-value]


def cmd_instruments(args: argparse.Namespace) -> None:
    """Get tradable instruments from /ref/v1/instruments endpoint"""
    params = {
        "$top": args.top,
        "AssetTypes": args.asset_type,
        "Keywords": args.keywords,
        "IncludeNonTradable": "false",
    }
    data = api_get("/ref/v1/instruments", params)
    items = data.get("Data", [])
    print(f"Found {len(items)} instruments for keywords='{args.keywords}':")
    for it in items:
        uic = it.get("Identifier")
        symbol = it.get("Symbol")
        desc = it.get("Description")
        asset_type = it.get("AssetType")
        print(f"- UIC={uic} | {symbol} | {asset_type} | {desc}")


def cmd_chart(args: argparse.Namespace) -> None:
    """Get OHLC samples for a given UIC with a simple Horizon and Count window
    from chart/v3/charts endpoint."""
    params = {
        "Uic": args.uic,
        "AssetType": args.asset_type,
        "Horizon": args.horizon,  # minutes; 1440 = daily
        "Count": args.count,
        "FieldGroups": "Data,DisplayAndFormat",
    }
    data = api_get("/chart/v3/charts", params)
    info = data.get("ChartInfo", {})
    rows = data.get("Data", [])
    symbol = data.get("DisplayAndFormat", {}).get("Symbol")
    print(f"{symbol or args.uic} | horizon={info.get('Horizon')} | samples={len(rows)}")
    for row in rows[:10]:
        print(
            f"{row['Time']}  "
            f"O:{row['Open']} H:{row['High']} L:{row['Low']} C:{row['Close']} "
            f"V:{row.get('Volume')}"
        )


def cmd_gpw_uics_from_list(args: argparse.Namespace) -> None:
    names = [
        "Asseco Poland SA",
        "Bank Handlowy w Warszawie SA",
        "Bank Polska Kasa Opieki SA",
        "Boryszew SA",
        "Globe Trade Centre SA",
        "Jastrzebska Spolka Weglowa SA",
        "Kernel Holding SA",
        "KGHM Polska Miedz SA",
        "LW Bogdanka SA",
        "PGE Polska Grupa Energetyczna SA",
        "ORLEN Spolka Akcyjna",
        "Powszechna Kasa Oszczednosci Bank Polski SA",
        "Powszechny Zaklad Ubezpieczen SA",
        "Tauron Polska Energia SA",
    ]

    with open("gpw_selected.csv", "w") as f:
        f.write("UIC,Name\n")
        for name in names:
            data = api_get("/ref/v1/instruments", {"Keywords": name, "AssetTypes": "Stock"})
            items = data.get("Data", [])
            if not items:
                print(f"Not found: {name}")
                continue
            first = items[0]
            f.write(f"{first['Identifier']},{first['Description']}\n")
            print(f"Found {first['Identifier']} for {name}")

    print("Saved gpw_selected.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="Minimal Saxo OpenAPI probe (SIM).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("instruments", help="Search instruments")
    p1.add_argument("--keywords", default="PKN", help="e.g. 'PKN' or 'EURUSD'")
    p1.add_argument("--asset-type", default="Stock", help="e.g. Stock, FxSport")
    p1.add_argument("--top", type=int, default=5, help="max results")
    p1.set_defaults(func=cmd_instruments)

    p2 = sub.add_parser("chart", help="Fetch recent OHLC samples")
    p2.add_argument("--uic", required=True, type=int, help="Instrument UIC")
    p2.add_argument("--asset-type", default="Stock")
    p2.add_argument("--horizon", type=int, default=1440, help="minutes (1440 daily)")
    p2.add_argument("--count", type=int, default=100, help="max samples (<=1200)")
    p2.set_defaults(func=cmd_chart)

    p5 = sub.add_parser("gpw_uics_from_list", help="Fetch UICs for listed GPW names")
    p5.set_defaults(func=cmd_gpw_uics_from_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
