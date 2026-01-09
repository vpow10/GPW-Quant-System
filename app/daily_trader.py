"""
Daily Trading Script
Executes the selected strategy on all available instruments.
Features:
- Detects Signal Changes (0->1 Buy, 1->0 Sell, 0->-1 Short, etc.)
- Auto-Allocation (Momentum Weighted)
- Long-Only Filter
"""
import argparse
import asyncio
import json
from datetime import datetime

import httpx
from dotenv import load_dotenv

from app.engine import LiveTrader

load_dotenv()


def get_live_eur_rate() -> float | None:
    """
    Fetches the current average EUR exchange rate from NBP API.
    Returns float rate (e.g. 4.3). Returns None on failure.
    """
    url = "http://api.nbp.pl/api/exchangerates/rates/a/eur/?format=json"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            mid = data["rates"][0]["mid"]
            return float(mid)
    except Exception as e:
        print(f"[!] Failed to fetch live EUR rate: {e}")
        return None


async def main():
    parser = argparse.ArgumentParser(description="Daily Trading Execution Script")
    parser.add_argument(
        "--strategy",
        type=str,
        default="momentum",
        help="Strategy name to run (default: momentum)",
    )
    parser.add_argument(
        "--amount",
        type=int,
        default=1,
        help="Default number of shares to trade per signal if auto-allocate is OFF (default: 1)",
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        default="momentum",
        help="Metric to sort/weight signals by (default: 'momentum').",
    )
    parser.add_argument(
        "--auto-allocate",
        action="store_true",
        help="If set, automatically allocates available cash weighted by signal strength (momentum).",
    )
    parser.add_argument(
        "--allocation-pct",
        type=float,
        default=1.0,
        help="Fraction of Total Cash to allocate (0.1 = 10%). Default 1.0 (100%).",
    )
    parser.add_argument(
        "--long-only",
        action="store_true",
        help="If set, only executes BUY (1) signals. Ignores SELL (-1) signals entirely.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="If set, REAL orders will be placed. Otherwise runs in dry-run mode.",
    )
    parser.add_argument(
        "--max-capital",
        type=float,
        default=500000.0,
        help="Maximum capital (EUR) to consider for trading. Defaults to 500k.",
    )
    parser.add_argument(
        "--max-daily-spend",
        type=float,
        default=50000.0,
        help="Maximum amount (EUR) to spend on new entries per day. Defaults to 50k.",
    )
    args = parser.parse_args()

    # Fetch Live Rate
    print("Fetching live EUR rate from NBP...")
    live_rate = get_live_eur_rate()
    if live_rate:
        fx_rate = live_rate
        print(f"Live EUR Rate: {fx_rate:.4f} PLN")
    else:
        fx_rate = 4.3
        print(f"[!] Using Fallback FX Rate: {fx_rate:.4f} PLN")

    print(f"Max Capital    : €{args.max_capital:,.2f}")
    print(f"Max Daily Spend: €{args.max_daily_spend:,.2f}")
    print(f"FX Rate        : {fx_rate}")

    trader = LiveTrader()

    total_cash = 0.0
    total_value = 0.0  # Net Equity to compare against Max Capital
    positions = []

    if args.auto_allocate or args.execute:
        w_res = trader.get_wallet()
        if "Data" in w_res and isinstance(w_res["Data"], list) and len(w_res["Data"]) > 0:
            data = w_res["Data"][0]
            total_cash = float(data.get("CashAvailableForTrading", 0.0))
            total_value = float(data.get("TotalValue", 0.0))  # NetEquity
        elif "CashAvailableForTrading" in w_res:
            total_cash = float(w_res["CashAvailableForTrading"])
            total_value = float(w_res.get("TotalValue", total_cash))
        elif "MarginAvailableForTrading" in w_res:
            total_cash = float(w_res["MarginAvailableForTrading"])
            total_value = float(w_res.get("TotalValue", total_cash))
        elif "CashBalance" in w_res:
            total_cash = float(w_res["CashBalance"])
            total_value = total_cash
        else:
            print(f"[!] Could not fetch wallet balance: {w_res}")
            return

        # Fetch Positions
        try:
            positions = trader.get_positions()
        except Exception as e:
            print(f"[!] Error fetching positions: {e}")
            positions = []

        if total_value == 0.0 and total_cash > 0:
            pass
    else:
        pass

    symbols = trader.list_symbols()
    print(f"Found {len(symbols)} instruments to analyze.")

    calculated_exposure_pln = 0.0
    held_qty_map = {p["uic"]: p["qty"] for p in positions}
    processed_uics = set()

    candidates = []

    # 2. Analyze all symbols
    for name, uic in symbols:
        try:
            res = trader.generate_signal(args.strategy, uic)

            if uic in held_qty_map:
                qty = held_qty_map[uic]
                price = res.get("close", 0.0)
                val_pln = qty * price
                calculated_exposure_pln += val_pln
                processed_uics.add(uic)

        except Exception as e:
            print(f"[!] Error analyzing {name} ({uic}): {e}")
            continue

        if "error" in res:
            continue

        curr = res.get("signal", 0)
        prev = res.get("prev_signal", 0)

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
            else:  # curr == 0
                if prev == 1:
                    action = "SELL"
                elif prev == -1:
                    action = "COVER"
                else:
                    continue

        res["uic"] = uic
        res["name"] = name
        res["action"] = action
        candidates.append(res)

    print(f"\nTotal Active Signals (Changes): {len(candidates)}")

    if not candidates:
        print("No signal changes today. No trades.")
        return

    for p in positions:
        if p["uic"] not in processed_uics:
            pass

    current_exposure_eur = calculated_exposure_pln / fx_rate

    global_remaining = args.max_capital - current_exposure_eur

    print("\n--- Limit Check (Recalculated) ---")
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

    # 3. Allocation & Sizing logic
    final_orders = []

    # Map UIC to held quantity for Exits
    # (Assuming single account, summing if multiple positions for same uic?? Saxo netpositions is 1 per uic usually)
    held_map = held_qty_map  # Reuse our map

    entries = [c for c in candidates if c["action"] in ("BUY", "SHORT")]
    exits = [c for c in candidates if c["action"] in ("SELL", "COVER")]

    # --- Process Entries ---
    def get_rank_score(item):
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

            final_daily_alloc = capped_2 * 0.95

            print(
                f"\nAllocating €{final_daily_alloc:,.2f} (Base: €{base_alloc_amt:,.2f}, GlobalRem: €{global_remaining:,.2f}, DailyCap: €{args.max_daily_spend:,.2f})"
            )

            for pick in valid_entries:
                score = get_rank_score(pick)
                weight = score / total_score
                allocated_eur = final_daily_alloc * weight

                allocated_pln = allocated_eur * fx_rate

                price = pick["close"]
                qty = int(allocated_pln / price)

                side = "Buy" if pick["action"] == "BUY" else "Sell"

                if qty >= 1:
                    final_orders.append(
                        {
                            "uic": pick["uic"],
                            "name": pick["name"],
                            "side": side,
                            "amount": qty,
                            "price": price,
                            "reason": f"Entry {pick['action']} (w={weight:.1%}) [€{allocated_eur:.0f} -> {allocated_pln:.0f} PLN]",
                        }
                    )
    elif entries:
        if usable_cash_for_entries <= 0 and args.auto_allocate:
            print("Skipping Entries: No Budget Available (Portfolio Limit or No Cash).")
        else:
            # Fixed amount mode
            for pick in entries:
                side = "Buy" if pick["action"] == "BUY" else "Sell"
                final_orders.append(
                    {
                        "uic": pick["uic"],
                        "name": pick["name"],
                        "side": side,
                        "amount": args.amount,
                        "price": pick["close"],
                        "reason": f"Entry {pick['action']} (Fixed - Check Limits Manually!)",
                    }
                )

    for pick in exits:
        side = "Sell" if pick["action"] == "SELL" else "Buy"
        uic = pick["uic"]

        # Check holdings
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

    # 4. Execution
    print(f"\n--- Planned Orders ({len(final_orders)}) ---")
    for order in final_orders:
        print(
            f"{order['side']:<4} {order['amount']:<4} x {order['name']:<10} @ {order['price']:.2f} | {order['reason']}"
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
            time.sleep(1.5)  #
    else:
        print("\n[DRY-RUN] No orders placed. Use --execute to trade.")

    report = {
        "timestamp": datetime.now().isoformat(),
        "strategy": args.strategy,
        "mode": "daily",
        "params": {
            "allocation_pct": args.allocation_pct,
            "max_capital": args.max_capital,
            "max_daily_spend": args.max_daily_spend,
            "long_only": args.long_only,
            "execute": args.execute,
        },
        "fx_rate": fx_rate,
        "wallet": {
            "total_value": total_value,
            "cash": total_cash,
            "currency": "EUR",
        },
        "exposure": {
            "calculated_pln": calculated_exposure_pln,
            "calculated_eur": current_exposure_eur,
            "remaining_eur": global_remaining,
        },
        "signals_found": len(candidates),
        "orders": final_orders,
    }

    report_path = "automation/daily_report.json"
    try:
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\n[Report] Saved execution report to {report_path}")
    except Exception as e:
        print(f"\n[!] Failed to save report: {e}")


if __name__ == "__main__":
    asyncio.run(main())
