"""Standarize raw Stooq CSVs into a clean daily pane for modeling."""
# ruff: noqa: T201
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = REPO_ROOT / "data" / "raw"
DATA_PROCESSED = REPO_ROOT / "data" / "processed"

PL_MAP = {
    "Data": "date",
    "Otwarcie": "open",
    "Najwyzszy": "high",
    "Najnizszy": "low",
    "Zamkniecie": "close",
    "Wolumen": "volume",
}


@dataclass
class Cfg:
    min_rows: int = 30  # skip files with less history than this
    abnormal_gap_z: float = 3.5  # z-score threshold for abnormal gaps flagging


CFG = Cfg()


def _read_raw(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns=PL_MAP)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df["volume"] = df["volume"].fillna(0).astype("int64")
    df = df.sort_values("date").drop_duplicates(subset=["date"])
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df[["date", "open", "high", "low", "close", "volume"]]


def _enrich(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    out = df.copy()
    out.insert(0, "symbol", symbol.lower())
    # 1-day simple return for sanity checks & future labels
    out["ret_1d"] = out["close"].pct_change()

    # robust z-score on returns to flag abnormal gaps
    r = out["ret_1d"]
    med = r.rolling(90, min_periods=30).median()
    mad = (r - med).abs().rolling(90, min_periods=30).median() * 1.4826
    robust_z = (r - med) / mad.replace(0, np.nan)
    out["flag_abnormal_gap"] = (robust_z.abs() > CFG.abnormal_gap_z).astype(int)

    return out


def _process_file(path: Path) -> Tuple[str, pd.DataFrame] | None:
    symbol = path.stem.lower()
    df = _read_raw(path)
    if len(df) < CFG.min_rows:
        print(f"[SKIP] {symbol}: only {len(df)} rows (< {CFG.min_rows})")
        return None
    out = _enrich(df, symbol)
    return symbol, out


def _save_symbol(df: pd.DataFrame, symbol: str) -> None:
    out_dir = DATA_PROCESSED / "gpw"
    out_dir.mkdir(parents=True, exist_ok=True)
    df[
        [
            "symbol",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "ret_1d",
            "flag_abnormal_gap",
        ]
    ].to_csv(out_dir / f"{symbol}.csv", index=False)
    try:
        df.to_parquet(out_dir / f"{symbol}.parquet", index=False)
    except Exception:
        pass  # parquet optional


def _write_report(panel: pd.DataFrame) -> None:
    rep_dir = DATA_PROCESSED / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    g = panel.groupby("symbol")
    report = pd.DataFrame(
        {
            "symbol": g.size().index,
            "rows": g.size().values,
            "start": g["date"].min().values,
            "end": g["date"].max().values,
            "n_gaps_flagged": g["flag_abnormal_gap"].sum().values,
        }
    )
    report = report.sort_values("symbol")
    report.to_csv(rep_dir / "_quality_report.csv", index=False)
    try:
        panel.to_parquet(rep_dir / "combined.parquet", index=False)
    except Exception:
        pass  # parquet optional
    panel.to_csv(rep_dir / "combined.csv", index=False)


def cmd_one(symbol: str) -> None:
    raw = DATA_RAW / f"{symbol.lower()}.csv"
    if not raw.exists():
        raise SystemExit(f"Missing raw file: {raw}. Run stooq_fetch.py first.")
    out = _process_file(raw)
    if not out:
        return
    sym, df = out
    _save_symbol(df, sym)
    print(f"[OK] processed {sym}: {len(df)} rows")


def cmd_all() -> None:
    processed = []
    for raw in sorted(DATA_RAW.glob("*.csv")):
        out = _process_file(raw)
        if not out:
            continue
        sym, df = out
        _save_symbol(df, sym)
        processed.append(df)
        print(f"[OK] {sym}: {len(df)} rows")
    if not processed:
        print("No files processed.")
        return
    panel = pd.concat(processed, ignore_index=True)
    _write_report(panel)
    print(f"Combined panel saved with {len(panel):,} rows and {panel.symbol.nunique()} symbols")


def main() -> None:
    p = argparse.ArgumentParser(description="Preprocess GPW raw CSVs -> standardized panel")
    p.add_argument("mode", choices=["one", "all"], help="Process single symbol or all")
    p.add_argument("--symbol", help="Required if mode=one")
    args = p.parse_args()

    if args.mode == "one":
        if not args.symbol:
            raise SystemExit("--symbol is required when mode=one")
        cmd_one(args.symbol)
    else:
        cmd_all()


if __name__ == "__main__":
    main()
