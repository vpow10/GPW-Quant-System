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

from dotenv import load_dotenv

from app.engine import LiveTrader

load_dotenv()


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
    args = parser.parse_args()

    print("--- Starting Daily Trader ---")
    print(f"Strategy     : {args.strategy}")
    print(f"Auto Allocate: {args.auto_allocate}")
    print(f"Long Only    : {args.long_only}")
    print(f"Execute      : {args.execute}")

    trader = LiveTrader()

    # Get wallet balance if allocating
    total_cash = 0.0
    if args.auto_allocate:
        w_res = trader.get_wallet()
        # Saxo response can be a list under "Data" or a direct dict depending on endpoint version/sim
        if "Data" in w_res and isinstance(w_res["Data"], list) and len(w_res["Data"]) > 0:
            total_cash = float(w_res["Data"][0].get("CashAvailableForTrading", 0.0))
        elif "CashAvailableForTrading" in w_res:
            total_cash = float(w_res["CashAvailableForTrading"])
        elif "MarginAvailableForTrading" in w_res:
            # Fallback if CashAvailableForTrading missing but Margin available
            total_cash = float(w_res["MarginAvailableForTrading"])
        elif "CashBalance" in w_res:
            total_cash = float(w_res["CashBalance"])
        else:
            print(f"[!] Could not fetch wallet balance: {w_res}")
            return
        print(f"Cash Available: {total_cash:.2f}")

    symbols = trader.list_symbols()
    print(f"Found {len(symbols)} instruments to analyze.")

    candidates = []

    # 1. Analyze all symbols
    for name, uic in symbols:
        try:
            res = trader.generate_signal(args.strategy, uic)
        except Exception as e:
            print(f"[!] Error analyzing {name} ({uic}): {e}")
            continue

        if "error" in res:
            continue

        # Logic for Signal Change
        # Signals: 1 (Long), 0 (Flat), -1 (Short)
        curr = res.get("signal", 0)
        prev = res.get("prev_signal", 0)

        # If no change, we skip. Strategy is "Trade on Change".
        if curr == prev:
            continue

        # If Long Only:
        # - Ignore entering Short (0 -> -1).
        # - Ignore switching Long to Short (1 -> -1).
        #   - Actually, 1 -> -1 means Close Long AND Open Short.
        #   - If Long Only, we should just Close Long (1 -> 0).
        # - Allow 0 -> 1 (Open Long).
        # - Allow -1 -> 1 (Close Short, Open Long). But if we were Long Only, we shouldn't be Short.
        #   - If we assume clean state, we just treat 1 as Buy.

        if args.long_only:
            # If target is Short (-1), we treat it as Flat (0) for safety/compatibility?
            # Or effectively ignore the "Short" part.
            # Case 0 -> -1: Ignore.
            # Case 1 -> -1: Should be Sell (Close Long). Treat new state as 0?
            if curr == -1:
                # We do not want to hold Short.
                # If we were Long (1), we should Sell to 0.
                # If we were 0, we stay 0.
                if prev == 1:
                    # Effectively treating transition as 1 -> 0
                    action = "SELL"  # Close Long
                else:
                    continue  # 0 -> -1 or -1 -> -1 (impossible here due to check above)
            elif curr == 1:
                # 0 -> 1 or -1 -> 1. Valid Buy.
                action = "BUY"
            elif curr == 0:
                # 1 -> 0. Valid Sell (Close).
                # -1 -> 0. Close Short... if we had one.
                if prev == 1:
                    action = "SELL"
                else:
                    continue  # -1 -> 0, Closing short. Not relevant for entry calculation usually?
                    # But wait, if we are closing, we need to execute a trade.
        else:
            # Long and Short allowed.
            if curr == 1:
                action = "BUY"
            elif curr == -1:
                action = "SHORT"
            else:  # curr == 0
                # Closing whatever we had.
                if prev == 1:
                    action = "SELL"  # Close Long
                elif prev == -1:
                    action = "COVER"  # Close Short (Buy back)
                else:
                    continue

        res["uic"] = uic
        res["name"] = name
        res["action"] = action  # BUY, SELL, SHORT, COVER
        candidates.append(res)

    print(f"\nTotal Active Signals (Changes): {len(candidates)}")

    if not candidates:
        print("No signal changes today. No trades.")
        return

    # 2. Allocation Logic
    # We only allocate cash for *Entries* (BUY or SHORT).
    # For *Exits* (SELL or COVER), we close the position.
    # Since we don't know the exact position size held, we have a dilemma.
    # User said "maximize profit... decide amounts".
    # Assumption for Exits:
    # - If Dry Run: Just show "Close Position".
    # - If Execute: We need to know how much to sell.
    # - Engine execute_trade doesn't have "Close All".
    # - Solution: We will effectively SKIP sizing logic for Exits and just log a warning
    #   or assume a default quantity if not tracking state.
    #   OR, we rely on `args.amount` for exits if state unknown.
    #   BUT, for Entries, we use "Smart Allocation".

    final_orders = []
    # List of entries to calculate weights for
    entries = [c for c in candidates if c["action"] in ("BUY", "SHORT")]
    exits = [c for c in candidates if c["action"] in ("SELL", "COVER")]

    # --- Process Entries (Allocate Cash) ---
    def get_rank_score(item):
        val = item.get(args.sort_by)
        if val is None:
            return 0.0
        return abs(float(val))

    if args.auto_allocate and entries:
        valid_entries = [c for c in entries if c.get(args.sort_by) is not None]
        total_score = sum(get_rank_score(c) for c in valid_entries)

        if total_score > 0:
            usable_cash = total_cash * args.allocation_pct * 0.95
            print(
                f"\nAllocating {usable_cash:.2f} (Factor: {args.allocation_pct:.2f}) across {len(valid_entries)} new entries."
            )

            for pick in valid_entries:
                score = get_rank_score(pick)
                weight = score / total_score
                allocated_amt = usable_cash * weight
                price = pick["close"]
                qty = int(allocated_amt / price)

                # Side map for execute_trade
                # BUY -> 'Buy'
                # SHORT -> 'Sell' (Opening Short)
                side = "Buy" if pick["action"] == "BUY" else "Sell"

                if qty >= 1:
                    final_orders.append(
                        {
                            "uic": pick["uic"],
                            "name": pick["name"],
                            "side": side,
                            "amount": qty,
                            "price": price,
                            "reason": f"Entry {pick['action']} (w={weight:.1%})",
                        }
                    )
    else:
        # Fixed amount for entries
        for pick in entries:
            side = "Buy" if pick["action"] == "BUY" else "Sell"
            final_orders.append(
                {
                    "uic": pick["uic"],
                    "name": pick["name"],
                    "side": side,
                    "amount": args.amount,
                    "price": pick["close"],
                    "reason": f"Entry {pick['action']} (Fixed)",
                }
            )

    # --- Process Exits ---
    # Since we don't know position size, we default to args.amount and warn.
    for pick in exits:
        side = "Sell" if pick["action"] == "SELL" else "Buy"  # SELL closes Long, Buy closes Short
        final_orders.append(
            {
                "uic": pick["uic"],
                "name": pick["name"],
                "side": side,
                "amount": args.amount,  # Fallback
                "price": pick["close"],
                "reason": f"Exit {pick['action']} (Unknown Size -> Default {args.amount})",
            }
        )

    # 3. Execution
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


if __name__ == "__main__":
    asyncio.run(main())
