"""
Core business logic for Live Execution.
"""
from __future__ import annotations

from typing import Any, cast

import httpx

from app.sync import NAME_MAP, UIC_MAP
from data.scripts.preprocess_gpw import process_symbol
from data.scripts.saxo_client import SaxoClient
from strategies.config_strategies import STRATEGY_CONFIG, get_strategy_class


class LiveTrader:
    def __init__(self) -> None:
        self.client = SaxoClient.from_env()
        self.uic_to_file = UIC_MAP
        self.file_to_uic = {v: k for k, v in UIC_MAP.items()}
        self.name_map = NAME_MAP

    def get_wallet(self) -> dict[str, Any]:
        url = f"{self.client.openapi_base}/port/v1/balances/me"
        headers = self.client._headers()

        with httpx.Client(timeout=10) as c:
            r = c.get(url, headers=headers)
            if r.status_code != 200:
                return {"error": f"HTTP {r.status_code}", "raw": r.text}

            data = r.json()

            if isinstance(data, dict):

                def _pick(*keys: str, default: float = 0.0) -> float:
                    for k in keys:
                        v = data.get(k)
                        if v is None:
                            continue
                        try:
                            return float(v)
                        except Exception:
                            pass
                    return default

                return {
                    "Currency": data.get("Currency"),
                    "CashAvailableForTrading": _pick(
                        "CashAvailableForTrading",
                        "MarginAvailableForTrading",
                        "CashBalance",
                        default=0.0,
                    ),
                    "TotalValue": _pick("TotalValue", default=0.0),
                    "raw": data,
                }

            return {"error": "Unexpected balances response shape", "raw": data}

    def list_strategies(self) -> list[str]:
        return list(STRATEGY_CONFIG.keys())

    def list_symbols(self) -> list[tuple[str, int]]:
        """Returns list of (Name, UIC)."""
        return [(self.name_map.get(k, str(k)), k) for k in self.uic_to_file.keys()]

    def generate_signal(self, strategy_name: str, uic: int) -> dict[str, Any]:
        """
        Runs the strategy on the *latest* local data for the given UIC.
        Returns the signal (-1, 0, 1) and metadata.
        """
        filename = self.uic_to_file.get(uic)
        if not filename:
            return {"error": f"Unknown UIC {uic}"}

        symbol_stem = filename.replace(".csv", "")

        df = process_symbol(symbol_stem)
        if df is None or df.empty:
            return {"error": f"No data for {symbol_stem}"}

        strat_cfg = STRATEGY_CONFIG.get(strategy_name, {})

        try:
            strategy_cls = get_strategy_class(strategy_name)
        except KeyError:
            return {"error": f"Unknown strategy {strategy_name}"}

        strategy = strategy_cls(**strat_cfg) if strat_cfg else strategy_cls()

        try:
            df_sig = strategy.generate_signals(df)
        except Exception as e:
            return {"error": f"Strategy failed: {e}"}

        last_row = df_sig.iloc[-1]

        result = cast("dict[str, Any]", last_row.to_dict())
        if hasattr(result["date"], "strftime"):
            result["date"] = result["date"].strftime("%Y-%m-%d")
        else:
            result["date"] = str(result["date"]).split(" ")[0]
        result["signal"] = int(result["signal"])
        result["close"] = float(result["close"])
        result["strategy"] = strategy_name

        sanitized_params = {}
        if isinstance(strategy.params, dict):
            for k, v in strategy.params.items():
                if hasattr(v, "__fspath__"):
                    sanitized_params[k] = str(v)
                else:
                    sanitized_params[k] = v
        else:
            sanitized_params = {"raw": str(strategy.params)}

        result["params"] = sanitized_params

        return result

    def execute_trade(
        self,
        uic: int,
        side: str,
        amount: int,
        order_type: str = "Market",
        price: float | None = None,
    ) -> dict[str, Any]:
        """
        Wraps SaxoClient.place_order.
        side: 'Buy' or 'Sell'
        """
        payload = self.client.build_order_payload(
            uic=uic,
            asset_type="Stock",
            side=side,
            amount=amount,
            order_type=order_type,
            price=price,
        )
        return self.client.place_order(payload)

    def get_positions(self) -> list[dict[str, Any]]:
        """
        Returns a list of open positions.
        Normalized to: [{'uic': 123, 'qty': 100, 'price': 12.5, 'id': '...'}, ...]
        """
        raw = self.client.get_net_positions()
        if "Data" not in raw:
            return []

        positions = []
        for item in raw["Data"]:
            if "NetPositionBase" in item:
                base = item["NetPositionBase"]
                view = item.get("NetPositionView", {})

                uic = base.get("Uic")
                qty = base.get("Amount", 0)

                p = {
                    "uic": uic,
                    "qty": qty,
                    "id": item.get("NetPositionId"),
                    "price": view.get("CurrentPrice", 0.0),
                    "market_value": view.get("MarketValueOpen", 0.0),
                }
            else:
                p = {
                    "uic": item.get("Uic"),
                    "qty": item.get("Amount", 0),
                    "id": item.get("NetPositionId"),
                    "price": item.get("CurrentPrice", 0.0),
                    "market_value": item.get("MarketValue", 0.0),
                }
            positions.append(p)
        return positions
