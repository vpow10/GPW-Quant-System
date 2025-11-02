# app_saxo_textual.py
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
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
)

from data.scripts.saxo_basic_poc import api_post, build_order_payload, log_json

# ---- konfig / .env ----
load_dotenv()
OPENAPI_BASE: str = os.getenv(
    "SAXO_OPENAPI_BASE", "https://gateway.saxobank.com/sim/openapi"
)
ACCOUNT_KEY: Optional[str] = os.getenv("SAXO_ACCOUNT_KEY")
TIMEOUT: int = int(os.getenv("SAXO_CLIENT_TIMEOUT", "30"))
LOG_DIR = Path(os.getenv("JOURNAL_DIR", "journals"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "orders.jsonl"


# ---- UI ----
class OrderUI(App):
    CSS = """
    Screen { layout: vertical; }
    #main   { height: 1fr; padding: 1; }
    #form   { padding: 1; border: round $primary; }
    #output { padding: 1; border: round $surface; height: 1fr; }
    Label { width: 16; }
    Input, Select, RadioSet { width: 1fr; }
    Button { margin-right: 1; }
    #status { padding: 1; }
    """

    BINDINGS = [
        ("ctrl+p", "preview", "Preview"),
        ("ctrl+o", "place", "Place"),
        ("q", "quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="form"):
                yield Label("UIC")
                yield Select(options=[("25275", 25275)], value=25275, id="uic")

                yield Label("AssetType")
                yield Select(options=[("Stock", "Stock")], value="Stock", id="asset")

                yield Label("Side")
                yield RadioSet(
                    RadioButton("Buy", value=True, id="buy"),
                    RadioButton("Sell", id="sell"),
                    id="side",
                )

                yield Label("Amount")
                yield Input(value="1", placeholder="float", id="amount")

                yield Label("OrderType")
                yield Select(options=[("Market", "Market")], value="Market", id="otype")

                yield Label("Price")
                yield Input(value="", placeholder="float", id="price")

                with Horizontal():
                    yield Button("Build payload", id="build", variant="primary")
                    yield Button("Preview", id="preview", variant="warning")
                    yield Button("Place", id="place", variant="success")
                    yield Button("Reset", id="reset")

                yield Label("", id="status")

            with Vertical(id="output"):
                yield Label("Payload")
                yield Log(id="payload")
                yield Label("Response")
                yield Log(id="response")
        yield Footer()

    def _read_form(self) -> dict[str, Any]:
        uic_val = self.query_one("#uic", Select).value
        if not isinstance(uic_val, (int, str)):
            raise ValueError("Select an instrument (UIC).")
        uic = int(uic_val)

        asset_val = self.query_one("#asset", Select).value
        if not isinstance(asset_val, str):
            raise ValueError("Select an Asset Type.")
        asset = asset_val

        side_rs = self.query_one("#side", RadioSet)
        side = (
            "Buy"
            if side_rs.pressed_button and side_rs.pressed_button.id == "buy"
            else "Sell"
        )

        amount_raw = self.query_one("#amount", Input).value.strip() or "1"
        try:
            amount = float(amount_raw)
        except ValueError:
            raise ValueError("Amount must be a number.")

        otype_val = self.query_one("#otype", Select).value
        if not isinstance(otype_val, str):
            raise ValueError("Select an Order Type.")
        otype = otype_val

        price_raw = self.query_one("#price", Input).value.strip()
        price: Optional[float] = float(price_raw) if price_raw else None

        return {
            "uic": uic,
            "asset_type": asset,
            "side": side,
            "amount": amount,
            "order_type": otype,
            "price": price,
        }

    def _set_status(self, text: str) -> None:
        self.query_one("#status", Label).update(text)

    def _show_payload(self, payload: dict[str, Any]) -> None:
        log = self.query_one("#payload", Log)
        log.clear()
        log.write_line(json.dumps(payload, indent=2, ensure_ascii=False))

    def _show_response(self, resp: Any) -> None:
        log = self.query_one("#response", Log)
        log.clear()
        log.write_line(json.dumps(resp, indent=2, ensure_ascii=False))

    async def _run_mode(self, place: bool) -> None:
        try:
            vals = self._read_form()
            payload = build_order_payload(**vals)
            self._show_payload(payload)
        except Exception as e:
            self._set_status(f"Błąd walidacji: {e}")
            return

        path = "/trade/v2/orders" if place else "/trade/v2/orders/preview"
        mode = "PLACE" if place else "PREVIEW"
        self._set_status(f"[{mode}] wysyłanie...")
        try:
            resp = api_post(path, payload)
            self._show_response(resp)
            log_json({"mode": mode, **vals, "payload": payload, "response": resp})
            self._set_status("Zamówienie złożone")
        except Exception as e:
            self._set_status(f"[{mode}] błąd: {e}")

    # ---- zdarzenia ----
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "build":
            try:
                payload = build_order_payload(**self._read_form())
                self._show_payload(payload)
                self._set_status("Payload zbudowany.")
            except Exception as e:
                self._set_status(f"Błąd: {e}")
        elif event.button.id == "preview":
            await self._run_mode(place=False)
        elif event.button.id == "place":
            await self._run_mode(place=True)
        elif event.button.id == "reset":
            self.query_one("#amount", Input).value = "1"
            self.query_one("#price", Input).value = ""
            self.query_one("#payload", Log).clear()
            self.query_one("#response", Log).clear()
            self._set_status("Wyczyszczono.")

    def action_preview(self) -> None:
        self.run_worker(self._run_mode(place=False), exclusive=True)

    def action_place(self) -> None:
        self.run_worker(self._run_mode(place=True), exclusive=True)


if __name__ == "__main__":
    OrderUI().run()
