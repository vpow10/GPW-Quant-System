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
    parser.add_argument(
        "--max-capital",
        type=float,
        default=500000.0,
        help="Maximum capital (USD) to consider for trading. Defaults to 500k.",
    )
    parser.add_argument(
        "--max-daily-spend",
        type=float,
        default=50000.0,
        help="Maximum amount (USD) to spend on new entries per day. Defaults to 50k.",
    )
    parser.add_argument(
        "--fx-rate",
        type=float,
        default=4.0,
        help="USD to PLN exchange rate for position sizing. Defaults to 4.0.",
    )
    args = parser.parse_args()

    print(f"Max Capital    : ${args.max_capital:,.2f}")
    print(f"Max Daily Spend: ${args.max_daily_spend:,.2f}")
    print(f"FX Rate        : {args.fx_rate}")

    trader = LiveTrader()

    # 1. Fetch Wallet & Positions
    # We need both to determine Total Equity and specific holdings for exits.
    total_cash = 0.0
    total_value = 0.0  # Net Equity to compare against Max Capital
    positions = []

    if args.auto_allocate or args.execute:
        # Fetch Wallet
        w_res = trader.get_wallet()
        if "Data" in w_res and isinstance(w_res["Data"], list) and len(w_res["Data"]) > 0:
            data = w_res["Data"][0]
            total_cash = float(data.get("CashAvailableForTrading", 0.0))
            total_value = float(data.get("TotalValue", 0.0))  # NetEquity
        elif "CashAvailableForTrading" in w_res:
            total_cash = float(w_res["CashAvailableForTrading"])
            # Fallback if structure is flat sim
            total_value = float(w_res.get("TotalValue", total_cash))
        elif "MarginAvailableForTrading" in w_res:
            total_cash = float(w_res["MarginAvailableForTrading"])
            total_value = float(w_res.get("TotalValue", total_cash))
        elif "CashBalance" in w_res:
            total_cash = float(w_res["CashBalance"])
            # Very old or basic struct
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
            # We defer strict pos value calculation to after the price loop
            pass
    else:
        # If not allocating/executing, simpler default
        pass

    symbols = trader.list_symbols()
    print(f"Found {len(symbols)} instruments to analyze.")

    # Track Exposure manually to fix 0-price API issue
    calculated_exposure_pln = 0.0
    held_qty_map = {p["uic"]: p["qty"] for p in positions}
    processed_uics = set()

    candidates = []

    # 2. Analyze all symbols
    for name, uic in symbols:
        try:
            res = trader.generate_signal(args.strategy, uic)

            # --- Exposure Tracking Fix ---
            if uic in held_qty_map:
                qty = held_qty_map[uic]
                price = res.get("close", 0.0)
                val_pln = qty * price
                calculated_exposure_pln += val_pln
                processed_uics.add(uic)
            # -----------------------------

        except Exception as e:
            print(f"[!] Error analyzing {name} ({uic}): {e}")
            continue

        if "error" in res:
            continue

        # Logic for Signal Change
        curr = res.get("signal", 0)
        prev = res.get("prev_signal", 0)

        # If no change, we skip. Strategy is "Trade on Change".
        if curr == prev:
            continue

        if args.long_only:
            # Long Only Logic
            if curr == -1:
                # If we were Long (1), we should Sell to 0.
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
            # Long/Short Logic
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
    # Limit Check & Alloc Init (Deferred)

    # Add any held positions that were NOT in the symbols list (fallback to API value)
    for p in positions:
        if p["uic"] not in processed_uics:
            # Use raw API value (might be 0, but best effort)
            # Note: API value is often in PLN for GPW stocks if account is EUR?
            # Actually API MarketValueOpenInBaseCurrency is EUR.
            # But here we sum PLN exposure for conversion.
            # If we don't know, ignore or use market_value from p
            # (which we tried to parse from View, might be 0)
            pass

    # Convert Exposure to USD
    current_exposure_usd = calculated_exposure_pln / args.fx_rate

    global_remaining = args.max_capital - current_exposure_usd

    print("\n--- Limit Check (Recalculated) ---")
    print(f"Calc Exposure  : {calculated_exposure_pln:,.2f} PLN (~${current_exposure_usd:,.2f})")
    print(f"Max Exposure Cap: ${args.max_capital:,.2f}")
    print(f"Exposure Remain : ${global_remaining:,.2f}")

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
            # Base Alloc Calculation
            # Allocation % applies to Total Cash available... or Limit?
            # Usually Alloc % is "Use 10% of my cash".
            # So base = total_cash * alloc_pct
            # But capped by global_remaining and daily_spend.

            base_alloc_amt = total_cash * args.allocation_pct

            # Cap 1: Global Limit Remaining
            capped_1 = min(base_alloc_amt, global_remaining)

            # Cap 2: Daily Spend Limit
            capped_2 = min(capped_1, args.max_daily_spend)

            final_daily_alloc = capped_2 * 0.95  # Safety buffer

            print(
                f"\nAllocating ${final_daily_alloc:,.2f} (Base: ${base_alloc_amt:,.2f}, GlobalRem: ${global_remaining:,.2f}, DailyCap: ${args.max_daily_spend:,.2f})"
            )

            for pick in valid_entries:
                score = get_rank_score(pick)
                weight = score / total_score
                allocated_usd = final_daily_alloc * weight

                # Convert USD -> PLN
                allocated_pln = allocated_usd * args.fx_rate

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
                            "reason": f"Entry {pick['action']} (w={weight:.1%}) [${allocated_usd:.0f} -> {allocated_pln:.0f} PLN]",
                        }
                    )
    elif entries:
        # Fallback if no cash or auto-alloc off
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

    # --- Process Exits (Smart Sizing) ---
    for pick in exits:
        side = "Sell" if pick["action"] == "SELL" else "Buy"
        uic = pick["uic"]

        # Check holdings
        held_qty = held_map.get(uic, 0)

        if held_qty > 0:
            qty_to_close = int(held_qty)  # Close full position logic for now?
            # Usually strict reversal means closing everything.
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
            # If we don't hold it, there's nothing to close.
            # Unless we are Shorting (COVER) and we didn't track it properly?
            # Safe bet: if 0 held, ignore or log.
            # But for testing, if we don't have positions data (e.g. error), we might fallback
            if not positions and not args.execute:
                # Dry run without fetching positions? Fallback
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


if __name__ == "__main__":
    asyncio.run(main())
