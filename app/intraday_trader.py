"""
Intraday Trading Script (e.g. hourly)
Fetches intraday OHLC from Saxo and runs any StrategyBase (e.g. LSTM).
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from typing import Any, cast

import httpx
import pandas as pd
from dotenv import load_dotenv

from app.engine import LiveTrader
from app.sync import NAME_MAP, UIC_MAP, fetch_intraday_ohlc
from strategies.config_strategies import STRATEGY_CONFIG, get_strategy_class

load_dotenv()


def build_intraday_df(uic: int, horizon_min: int, count: int) -> pd.DataFrame:
    rows = fetch_intraday_ohlc(uic, horizon=horizon_min, limit=count)
    if not rows:
        return pd.DataFrame()

    symbol_stem = UIC_MAP.get(uic, "").replace(".csv", "")

    ts_local = (
        pd.to_datetime([r["Time"] for r in rows], utc=True)
        .tz_convert("Europe/Warsaw")
        .tz_localize(None)
    )

    data = []
    for dt, r in zip(ts_local, rows):
        data.append(
            {
                "symbol": symbol_stem.lower(),
                "date": dt,
                "open": float(r["Open"]),
                "high": float(r["High"]),
                "low": float(r["Low"]),
                "close": float(r["Close"]),
                "volume": int(r.get("Volume") or 0),
            }
        )

    df = pd.DataFrame(data)
    if df.empty:
        return df

    df = df.sort_values("date")
    df["ret_1d"] = df["close"].pct_change()
    df["flag_abnormal_gap"] = 0
    return df


def get_live_eur_rate() -> float | None:
    """
    Fetches the current average EUR exchange rate from NBP API.
    Returns float rate (e.g. 4.3). Returns None on failure.
    """
    url = "http://api.nbp.pl/api/exchangerates/rates/a/eur/?format=json"
    try:
        # Timeout 5s is usually enough for NBP
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            # data structure: {"rates": [{"mid": 4.3, ...}]}
            mid = data["rates"][0]["mid"]
            return float(mid)
    except Exception as e:
        print(f"[!] Failed to fetch live EUR rate: {e}")
        return None


async def main() -> None:
    parser = argparse.ArgumentParser(description="Intraday Trading Execution Script")
    parser.add_argument(
        "--strategy",
        type=str,
        default="lstm",
        help="Strategy name to run (e.g. lstm, hybrid_lstm_10d, momentum).",
    )
    parser.add_argument(
        "--amount",
        type=int,
        default=1,
        help="Default number of shares per signal if auto-allocate is OFF.",
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        default="signal_strength",
        help="Metric to sort/weight signals by (e.g. 'momentum', 'hybrid_pred', etc.).",
    )
    parser.add_argument(
        "--auto-allocate",
        action="store_true",
        help="Automatically allocate cash weighted by |sort-by|.",
    )
    parser.add_argument(
        "--allocation-pct",
        type=float,
        default=0.2,
        help="Fraction of total cash to allocate per run (0.2 = 20%%).",
    )
    parser.add_argument(
        "--long-only",
        action="store_true",
        help="Only execute long-side of signals; shorts ignored.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="If set, REAL orders will be placed. Otherwise dry-run.",
    )
    parser.add_argument(
        "--max-capital",
        type=float,
        default=500000.0,
        help="Max portfolio exposure (USD-equivalent).",
    )
    parser.add_argument(
        "--max-daily-spend",
        type=float,
        default=100000.0,
        help="Max fresh spend per day in USD-equivalent.",
    )
    parser.add_argument(
        "--fx-rate",
        type=float,
        default=4.0,
        help="USD/PLN FX rate for converting exposure and budgets.",
    )
    parser.add_argument(
        "--horizon-min",
        type=int,
        default=60,
        help="Intraday bar horizon in minutes (e.g. 60 = hourly).",
    )
    parser.add_argument(
        "--lookback-bars",
        type=int,
        default=200,
        help="Number of recent intraday bars per symbol to feed into the strategy.",
    )
    args = parser.parse_args()

    # Fetch Live Rate
    print("Fetching live EUR rate from NBP...")
    live_rate = get_live_eur_rate()
    if live_rate:
        args.fx_rate = live_rate
        print(f"Live EUR Rate: {args.fx_rate:.4f} PLN")
    else:
        print(f"[!] Using Fallback FX Rate: {args.fx_rate:.4f} PLN")

    print(f"Strategy       : {args.strategy}")
    print(f"Bar Horizon    : {args.horizon_min} min")
    print(f"Lookback Bars  : {args.lookback_bars}")
    print(f"Max Capital    : €{args.max_capital:,.2f}")
    print(f"Max Daily Spend: €{args.max_daily_spend:,.2f}")
    print(f"FX Rate        : {args.fx_rate} (EUR/PLN)")

    trader = LiveTrader()

    strat_cfg = STRATEGY_CONFIG.get(args.strategy, {})
    try:
        strat_cls = get_strategy_class(args.strategy)
    except KeyError:
        print(f"[!] Strategy {args.strategy} not found.")
        return

    strategy = strat_cls(**strat_cfg) if strat_cfg else strat_cls()

    total_cash = 0.0
    total_value = 0.0
    positions: list[dict[str, Any]] = []

    if args.auto_allocate or args.execute:
        w_res = trader.get_wallet()
        if "error" in w_res:
            print(f"[!] Could not fetch wallet balance: {w_res}")
            return

        total_cash = float(w_res.get("CashAvailableForTrading", 0.0))
        total_value = float(w_res.get("TotalValue", total_cash))
        print(
            f"[wallet] ccy={w_res.get('Currency')} "
            f"total_cash={total_cash:.2f} total_value={total_value:.2f}"
        )

        try:
            positions = trader.get_positions()
        except Exception as e:
            print(f"[!] Error fetching positions: {e}")
            positions = []
    else:
        pass

    symbols = [(NAME_MAP.get(u, str(u)), u) for u in UIC_MAP.keys()]
    print(f"Found {len(symbols)} instruments to analyze intraday.")

    calculated_exposure_pln = 0.0
    held_qty_map = {p["uic"]: p["qty"] for p in positions}
    processed_uics: set[int] = set()
    candidates: list[dict[str, Any]] = []

    for name, uic in symbols:
        try:
            df_intr = build_intraday_df(uic, args.horizon_min, args.lookback_bars)
            if df_intr.empty:
                continue

            df_sig = strategy.generate_signals(df_intr)
            if df_sig.empty:
                continue

            last_row = df_sig.iloc[-1]
            # Ensure dict[str, Any] for mypy
            res = cast("dict[str, Any]", last_row.to_dict())
            res["date"] = str(res["date"])
            res["signal"] = int(res.get("signal", 0))
            res["prev_signal"] = int(res.get("prev_signal", 0))
            res["close"] = float(res["close"])
            res["strategy"] = args.strategy
            res["params"] = str(strategy.params)
            res["uic"] = uic
            res["name"] = name

            if uic in held_qty_map:
                qty = held_qty_map[uic]
                price = res["close"]
                val_pln = qty * price
                calculated_exposure_pln += val_pln
                processed_uics.add(uic)
        except Exception as e:
            print(f"[!] Error analyzing {name} ({uic}): {e}")
            continue

        curr = res["signal"]
        prev = res["prev_signal"]

        if curr == prev:
            continue

        if args.long_only:
            if curr == -1:
                if prev == 1:
                    action = "SELL"
                else:
                    continue
            elif curr == 1:
                action = "BUY"
            elif curr == 0:
                if prev == 1:
                    action = "SELL"
                else:
                    continue
        else:
            if curr == 1:
                action = "BUY"
            elif curr == -1:
                action = "SHORT"
            else:
                if prev == 1:
                    action = "SELL"
                elif prev == -1:
                    action = "COVER"
                else:
                    continue

        res["action"] = action
        candidates.append(res)

    print("\n--- Candidates (signal changes) ---")
    for c in candidates:
        print(
            f"{c['name']} (uic={c['uic']}) action={c.get('action')} "
            f"signal {c.get('prev_signal')} -> {c.get('signal')} "
            f"close={c.get('close')} hybrid_pred={c.get('hybrid_pred')}"
        )

    print(f"\nTotal Active Signals (Changes): {len(candidates)}")
    if not candidates:
        print("No signal changes this run. No trades.")
        # Do not return early, proceed to report generation

    # User simplified logic: Exposure = TotalValue - TotalCash (in account currency, presumably EUR)
    # This avoids relying on manual position tracking
    current_exposure_eur = max(0.0, total_value - total_cash)
    global_remaining = args.max_capital - current_exposure_eur

    # Back-calculate PLN for consistent logging
    # Back-calculate PLN for consistent logging
    calculated_exposure_pln = current_exposure_eur * args.fx_rate

    print("\n--- Limit Check (Intraday) ---")
    print(f"Calc Exposure  : {calculated_exposure_pln:,.2f} PLN (~€{current_exposure_eur:,.2f})")
    print(f"Max Exposure Cap: €{args.max_capital:,.2f}")
    print(f"Exposure Remain : €{global_remaining:,.2f}")

    if args.auto_allocate or args.execute:
        if global_remaining <= 0:
            print("[!] Max Exposure Limit reached. No new entries allowed.")
            usable_cash_for_entries = 0.0
        else:
            usable_cash_for_entries = min(total_cash, global_remaining)
    else:
        usable_cash_for_entries = 0.0

    final_orders: list[dict[str, Any]] = []
    held_map = held_qty_map

    entries = [c for c in candidates if c["action"] in ("BUY", "SHORT")]
    exits = [c for c in candidates if c["action"] in ("SELL", "COVER")]

    def get_rank_score(item: dict[str, Any]) -> float:
        val = item.get(args.sort_by)
        if val is None:
            return 0.0
        return abs(float(val))

    if args.auto_allocate and entries and usable_cash_for_entries > 0:
        valid_entries = [c for c in entries if c.get(args.sort_by) is not None]
        total_score = sum(get_rank_score(c) for c in valid_entries)

        if total_score > 0:
            base_alloc_amt = total_cash * args.allocation_pct
            capped_1 = min(base_alloc_amt, global_remaining)
            capped_2 = min(capped_1, args.max_daily_spend)
            final_alloc_eur = capped_2 * 0.95

            print(
                f"\nAllocating €{final_alloc_eur:,.2f} "
                f"(Base: €{base_alloc_amt:,.2f}, GlobalRem: €{global_remaining:,.2f}, "
                f"DailyCap: €{args.max_daily_spend:,.2f})"
            )

            for pick in valid_entries:
                score = get_rank_score(pick)
                weight = score / total_score
                allocated_eur = final_alloc_eur * weight
                allocated_pln = allocated_eur * args.fx_rate

                price = pick["close"]
                qty = int(allocated_pln / price)

                if qty < 1:
                    # try minimum order = 1 if we can afford it
                    if allocated_pln >= price:
                        qty = 1
                    else:
                        # not enough allocation to buy 1 share
                        continue
                side = "Buy" if pick["action"] == "BUY" else "Sell"

                if qty >= 1:
                    final_orders.append(
                        {
                            "uic": pick["uic"],
                            "name": pick["name"],
                            "side": side,
                            "amount": qty,
                            "price": price,
                            "reason": (
                                f"Entry {pick['action']} "
                                f"(w={weight:.1%}) [€{allocated_eur:.0f} -> {allocated_pln:.0f} PLN]"
                            ),
                        }
                    )
    elif entries:
        if usable_cash_for_entries <= 0 and args.auto_allocate:
            print("Skipping Entries: No Budget Available (Portfolio Limit or No Cash).")
        else:
            for pick in entries:
                side = "Buy" if pick["action"] == "BUY" else "Sell"
                final_orders.append(
                    {
                        "uic": pick["uic"],
                        "name": pick["name"],
                        "side": side,
                        "amount": args.amount,
                        "price": pick["close"],
                        "reason": f"Entry {pick['action']} (Fixed size)",
                    }
                )

    for pick in exits:
        side = "Sell" if pick["action"] == "SELL" else "Buy"
        uic = pick["uic"]
        held_qty = held_map.get(uic, 0)

        if held_qty > 0:
            qty_to_close = int(held_qty)
            final_orders.append(
                {
                    "uic": uic,
                    "name": pick["name"],
                    "side": side,
                    "amount": qty_to_close,
                    "price": pick["close"],
                    "reason": f"Exit {pick['action']} (Closing Held Position: {held_qty})",
                }
            )
        else:
            if not positions and not args.execute:
                final_orders.append(
                    {
                        "uic": uic,
                        "name": pick["name"],
                        "side": side,
                        "amount": args.amount,
                        "price": pick["close"],
                        "reason": f"Exit {pick['action']} (No Pos Data -> Default {args.amount})",
                    }
                )
            else:
                print(f"Skipping Exit {pick['name']}: No positions held.")

    print(f"\n--- Planned Orders ({len(final_orders)}) ---")
    for order in final_orders:
        print(
            f"{order['side']:<4} {order['amount']:<4} x {order['name']:<10} "
            f"@ {order['price']:.2f} | {order['reason']}"
        )

    if args.execute:
        import time

        print("\n--- Executing Orders ---")
        for order in final_orders:
            print(f"Executing {order['side']} {order['amount']} x {order['name']}...")
            try:
                res = trader.execute_trade(order["uic"], order["side"], order["amount"])
                print(f"  Result: {res}")
            except Exception as e:
                print(f"  FAILED: {e}")
            time.sleep(1.5)
    else:
        print("\n[DRY-RUN] No orders placed. Use --execute to trade.")

    # 5. Generate JSON Report
    report = {
        "timestamp": datetime.now().isoformat(),
        "strategy": args.strategy,
        "mode": "intraday",
        "params": {
            "allocation_pct": args.allocation_pct,
            "max_capital": args.max_capital,
            "max_daily_spend": args.max_daily_spend,
            "long_only": args.long_only,
            "execute": args.execute,
            "horizon_min": args.horizon_min,
        },
        "fx_rate": args.fx_rate,
        "wallet": {"total_value": total_value, "cash": total_cash, "currency": "EUR"},
        "exposure": {
            "calculated_pln": calculated_exposure_pln,
            "calculated_eur": current_exposure_eur,
            "remaining_eur": global_remaining,
        },
        "signals_found": len(candidates),
        "orders": final_orders,
    }

    report_path = "automation/intraday_report.json"
    try:
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n[Report] Saved execution report to {report_path}")
    except Exception as e:
        print(f"\n[!] Failed to save report: {e}")


if __name__ == "__main__":
    asyncio.run(main())
