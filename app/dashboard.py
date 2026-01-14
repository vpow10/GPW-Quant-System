"""
Textual Dashboard for Live Trading System.
"""
from __future__ import annotations

import asyncio
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    Log,
    RadioButton,
    RadioSet,
    Select,
    TabbedContent,
    TabPane,
)

from app.engine import LiveTrader
from app.sync import sync_gpw_data


class Dashboard(App):
    CSS = """
    Screen { layout: vertical; }
    .box { border: round $primary; padding: 1; margin: 1; height: auto; }
    .sidebar { width: 20%; dock: left; }
    .main { width: 1fr; }

    /* Monitor Tab */
    #monitor-log { height: 1fr; border: solid $secondary; }

    /* Auto Tab */
    #signal-output { height: 10; border: solid $accent; background: $surface; }
    .big-button { height: 3; width: 1fr; }

    /* Manual Tab */
    Label { width: 16; }
    Input, Select, RadioSet { width: 1fr; }
    .form-row { height: auto; margin-bottom: 1; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.trader = LiveTrader()
        self.last_signal: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with TabbedContent(initial="monitor"):
            # --- TAB 1: MONITOR & SYNC ---
            with TabPane("Monitor", id="monitor"):
                with Horizontal():
                    with Vertical(classes="box"):
                        yield Label("ACCOUNT STATUS", classes="header")
                        yield Button("Refresh Balance", id="btn-balance")
                        yield Label("...", id="lbl-balance")

                    with Vertical(classes="box"):
                        yield Label("DATA SYNC", classes="header")
                        yield Button("Sync GPW Data", id="btn-sync", variant="warning")

                yield Log(id="monitor-log")

            # --- TAB 2: AUTO / STRATEGIES ---
            with TabPane("Auto Strategies", id="auto"):
                with Horizontal():
                    with Vertical(classes="box"):
                        yield Label("Select Strategy")
                        strategies = [(s, s) for s in self.trader.list_strategies()]
                        yield Select(strategies, prompt="Select Strategy", id="sel-strat")

                        yield Label("Select Instrument")
                        symbols = self.trader.list_symbols()  # [(Name, UIC), ...]
                        # Select expects (label, value)
                        yield Select(symbols, prompt="Select Company", id="sel-symbol")

                        yield Button(
                            "Analyze / Generate Signal",
                            id="btn-analyze",
                            variant="primary",
                            classes="big-button",
                        )

                    with Vertical(classes="box main"):
                        yield Label("Analysis Result")
                        yield Label("...", id="lbl-signal")
                        yield Label("", id="lbl-explain")

                        with Horizontal(classes="form-row"):
                            yield Label("Amount:")
                            yield Input("1", id="auto-amount")

                        yield Button(
                            "Execute Signal (Trade)",
                            id="btn-auto-trade",
                            variant="error",
                            disabled=True,
                        )
                        yield Log(id="auto-log")

            # --- TAB 3: MANUAL TRADE ---
            with TabPane("Manual Trade", id="manual"):
                with VerticalScroll():
                    with Vertical(classes="box"):
                        yield Label("MANUAL ORDER FORM")
                        yield Select(
                            self.trader.list_symbols(), prompt="Instrument", id="man-uic"
                        )
                        yield Select(
                            [("Stock", "Stock")], value="Stock", id="man-asset", disabled=True
                        )
                        yield RadioSet(
                            RadioButton("Buy", value=True, id="man-buy"),
                            RadioButton("Sell", id="man-sell"),
                            id="man-side",
                        )
                        yield Input(placeholder="Amount", value="1", id="man-amount")
                        yield Select(
                            [("Market", "Market"), ("Limit", "Limit")],
                            value="Market",
                            id="man-type",
                        )
                        yield Input(
                            placeholder="Price (Limit only)", id="man-price", disabled=True
                        )

                        with Horizontal():
                            yield Button("Place Order", id="btn-man-place", variant="success")
                            yield Button("Preview", id="btn-man-preview")

                        yield Log(id="man-log")

        yield Footer()

    # --- ACTIONS & HANDLERS ---

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id == "btn-sync":
            self.query_one("#monitor-log", Log).write_line("Sync started...")
            self.run_worker(self.action_sync(), exclusive=True)

        elif btn_id == "btn-balance":
            self.run_worker(self.action_balance())

        elif btn_id == "btn-analyze":
            await self.action_analyze()

        elif btn_id == "btn-auto-trade":
            await self.action_auto_trade()

        elif btn_id == "btn-man-place":
            await self.action_manual_trade(preview=False)

        elif btn_id == "btn-man-preview":
            await self.action_manual_trade(preview=True)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "man-type":
            is_limit = str(event.value) == "Limit"
            self.query_one("#man-price", Input).disabled = not is_limit

    # --- WORKERS ---

    async def action_sync(self) -> None:
        log = self.query_one("#monitor-log", Log)
        try:
            loop = asyncio.get_running_loop()
            logs = await loop.run_in_executor(None, sync_gpw_data)
            for msg in logs:
                log.write_line(msg)
            log.write_line("Sync complete.")
        except Exception as e:
            log.write_line(f"Sync failed: {e}")

    async def action_balance(self) -> None:
        lbl = self.query_one("#lbl-balance", Label)
        lbl.update("Fetching...")
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, self.trader.get_wallet)
        if "Data" in res and isinstance(res["Data"], list) and len(res["Data"]) > 0:
            bal = res["Data"][0]
            txt = (
                f"Total Value: {bal.get('TotalValue', '?')} {bal.get('Currency', '')}\n"
                f"Cash Avail : {bal.get('CashAvailableForTrading', '?')}"
            )
            lbl.update(txt)
        else:
            lbl.update(str(res))

    async def action_analyze(self) -> None:
        strat = self.query_one("#sel-strat", Select).value
        uic = self.query_one("#sel-symbol", Select).value
        log = self.query_one("#auto-log", Log)

        if not strat or not uic:
            log.write_line("Error: Select strategy and symbol.")
            return

        log.write_line(f"Analyzing {uic} with {strat}...")

        loop = asyncio.get_running_loop()

        if uic == Select.BLANK:
            log.write_line("Select instrument!")
            return

        s_val = str(strat)
        u_val = int(str(uic))
        res = await loop.run_in_executor(None, self.trader.generate_signal, s_val, u_val)

        if "error" in res:
            self.query_one("#lbl-signal", Label).update(f"ERROR: {res['error']}")
            self.query_one("#btn-auto-trade", Button).disabled = True
            return

        sig = res["signal"]

        # Interpret signal
        if sig == 1:
            text = "BULLISH (Long)"
        elif sig == -1:
            text = "BEARISH (Short)"
        else:
            text = "NEUTRAL (Flat)"

        self.query_one("#lbl-signal", Label).update(f"Signal: {text} | Date: {res['date']}")
        self.query_one("#lbl-explain", Label).update(str(res.get("params", "")))

        # Enable trade only if not neutral
        btn = self.query_one("#btn-auto-trade", Button)
        if sig != 0:
            btn.disabled = False
            btn.label = f"Execute {text}"
            self.last_signal = {"uic": uic, "signal": sig}
        else:
            btn.disabled = True
            self.last_signal = None

    async def action_auto_trade(self) -> None:
        if not self.last_signal:
            return

        uic = self.last_signal["uic"]
        sig = self.last_signal["signal"]
        amount_str = self.query_one("#auto-amount", Input).value
        try:
            amount = int(amount_str)
        except Exception:
            self.query_one("#auto-log", Log).write_line("Invalid amount.")
            return

        side = "Buy" if sig == 1 else "Sell"
        log = self.query_one("#auto-log", Log)
        log.write_line(f"Placing {side} order for {amount} shares...")

        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(
            None, self.trader.execute_trade, int(uic), side, int(amount)
        )

        log.write_line(f"Result: {res}")

    async def action_manual_trade(self, preview: bool) -> None:
        log = self.query_one("#man-log", Log)
        try:
            uic = self.query_one("#man-uic", Select).value
            if uic == Select.BLANK:
                raise ValueError("Select Instrument")
            u_val = int(str(uic))

            side_rs = self.query_one("#man-side", RadioSet)
            if not side_rs.pressed_button:
                raise ValueError("Select Side")
            side = "Buy" if side_rs.pressed_button.id == "man-buy" else "Sell"

            amt_str = self.query_one("#man-amount", Input).value
            amount = float(amt_str)

            otype_val = self.query_one("#man-type", Select).value
            if otype_val == Select.BLANK:
                raise ValueError("Select Order Type")
            otype = str(otype_val)

            price = None
            if otype == "Limit":
                p_str = self.query_one("#man-price", Input).value
                if not p_str:
                    raise ValueError("Limit requires price")
                price = float(p_str)

            # Execution
            loop = asyncio.get_running_loop()
            if preview:
                log.write_line("Preview not fully implemented in Engine yet.")
            else:
                log.write_line(f"Placing {side} {amount}...")
                res = await loop.run_in_executor(
                    None, self.trader.execute_trade, u_val, side, int(amount), otype, price
                )
                log.write_line(str(res))

        except Exception as e:
            log.write_line(f"Error: {e}")


if __name__ == "__main__":
    Dashboard().run()
