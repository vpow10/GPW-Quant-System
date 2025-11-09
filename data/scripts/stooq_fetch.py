"""Fetch historical stock data from Stooq.pl and save as Parquet files."""
# ruff: noqa: T201
from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import httpx
import pandas as pd

NAME_TO_STOOQ: dict[str, str] = {
    "Asseco Poland SA": "acp",
    "Bank Handlowy w Warszawie SA": "bhw",
    "Bank Polska Kasa Opieki SA": "peo",
    "Boryszew SA": "brs",
    "Globe Trade Centre SA": "gtc",
    "Jastrzebska Spolka Weglowa SA": "jsw",
    "Kernel Holding SA": "ker",
    "LW Bogdanka SA": "lwb",
    "PGE Polska Grupa Energetyczna SA": "pge",
    "ORLEN Spolka Akcyjna": "pkn",
    "Powszechna Kasa Oszczednosci Bank Polski SA": "pko",
    "Powszechny Zaklad Ubezpieczen SA": "pzu",
    "Tauron Polska Energia SA": "tpe",
    "KGHM Polska Miedz SA": "kgh",
}

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = REPO_ROOT / "data" / "raw"
GPW_SELECTED = REPO_ROOT / "gpw_selected.csv"

STOOQ_BASE = "https://stooq.pl/q/d/l/"


def _ymd(d: date | None) -> str | None:
    if d is None:
        return None
    return d.strftime("%Y%m%d")


def build_url(
    symbol: str, interval: str = "d", start: date | None = None, end: date | None = None
) -> str:
    """
    interval: 'd' daily, 'w' weekly, 'm' monthly
    """
    qs = [f"s={symbol.lower()}", f"i={interval}"]
    if start:
        qs.append(f"d1={_ymd(start)}")
    if end:
        qs.append(f"d2={_ymd(end)}")
    return f"{STOOQ_BASE}?{'&'.join(qs)}"


def fetch_csv(
    symbol: str, interval: str = "d", start: date | None = None, end: date | None = None
) -> bytes:
    if start is None:
        start = date(2000, 1, 1)
    if end is None:
        end = date.today()
    url = build_url(symbol, interval, start, end)
    with httpx.Client(timeout=20.0) as client:
        r = client.get(url, headers={"User-Agent": "gpw-quant-system/1.0"})
        r.raise_for_status()
        content = r.content
        if content.count(b"\n") < 2:  # no data, too few lines
            raise RuntimeError(f"Empty/invalid CSV for {symbol} from {url}")
        return content


def save_raw(symbol: str, payload: bytes) -> Path:
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    out = DATA_RAW / f"{symbol.lower()}.csv"
    out.write_bytes(payload)
    return out


def read_gpw_selected_names() -> list[str]:
    df = pd.read_csv(GPW_SELECTED)
    return list(df["Name"].astype(str))


def names_to_symbols(names: Iterable[str]) -> dict[str, str]:
    missing: list[str] = []
    mapping: dict[str, str] = {}
    for n in names:
        sym = NAME_TO_STOOQ.get(n)
        if not sym:
            missing.append(n)
        else:
            mapping[n] = sym
    if missing:
        raise SystemExit(
            "No Stooq mapping for:\n  - "
            + "\n  - ".join(missing)
            + "\nAdd them to NAME_TO_STOOQ dictionary in stooq_fetch.py"
        )
    return mapping


def cmd_fetch_one(args: argparse.Namespace) -> None:
    start = datetime.fromisoformat(args.start).date() if args.start else None
    end = datetime.fromisoformat(args.end).date() if args.end else None
    payload = fetch_csv(args.symbol, args.interval, start, end)
    out = save_raw(args.symbol, payload)
    print(f"Saved: {out}")


def cmd_fetch_all(args: argparse.Namespace) -> None:
    names = read_gpw_selected_names()
    mapping = names_to_symbols(names)
    start = datetime.fromisoformat(args.start).date() if args.start else None
    end = datetime.fromisoformat(args.end).date() if args.end else None
    ok, fail = 0, 0
    for name, symbol in mapping.items():
        try:
            payload = fetch_csv(symbol, args.interval, start, end)
            out = save_raw(symbol, payload)
            print(f"[OK]  {name} -> {symbol} -> {out.name}")
            ok += 1
        except Exception as e:
            print(f"[FAIL] {name} -> {symbol}: {e}")
            fail += 1
    print(f"Done. ok={ok} fail={fail}")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Fetch GPW historical OHLCV from Stooq and save to data/raw/"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("fetch-one", help="Fetch one symbol")
    p1.add_argument("symbol", help="Stooq symbol, e.g. 'pko'")
    p1.add_argument("--interval", default="d", choices=["d", "w", "m"])
    p1.add_argument("--start", default=None, help="YYYY-MM-DD (optional)")
    p1.add_argument("--end", default=None, help="YYYY-MM-DD (optional)")
    p1.set_defaults(func=cmd_fetch_one)

    p2 = sub.add_parser("fetch-all", help="Fetch for gpw_selected.csv (mapped)")
    p2.add_argument("--interval", default="d", choices=["d", "w", "m"])
    p2.add_argument("--start", default=None, help="YYYY-MM-DD (optional)")
    p2.add_argument("--end", default=None, help="YYYY-MM-DD (optional)")
    p2.set_defaults(func=cmd_fetch_all)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
