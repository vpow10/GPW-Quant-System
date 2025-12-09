"""
Core business logic for Live Execution.
"""
from __future__ import annotations

from typing import Any

from app.sync import NAME_MAP, UIC_MAP
from data.scripts.preprocess_gpw import process_symbol
from data.scripts.saxo_client import SaxoClient
from strategies.config_strategies import STRATEGY_CONFIG, STRATEGY_REGISTRY


class LiveTrader:
    def __init__(self) -> None:
        self.client = SaxoClient.from_env()
        self.uic_to_file = UIC_MAP
        self.file_to_uic = {v: k for k, v in UIC_MAP.items()}
        self.name_map = NAME_MAP

    def get_wallet(self) -> dict[str, Any]:
        """Fetch account balance summary."""
        import httpx

        url = f"{self.client.openapi_base}/port/v1/balances/me"
        headers = self.client._headers()

        with httpx.Client(timeout=10) as c:
            r = c.get(url, headers=headers)
            if r.status_code == 200:
                return r.json()
            return {"error": f"HTTP {r.status_code}", "raw": r.text}

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

        # 1. Preprocess (load data)
        df = process_symbol(symbol_stem)
        if df is None or df.empty:
            return {"error": f"No data for {symbol_stem}"}

        # 2. Load Strategy
        strat_cls = STRATEGY_REGISTRY.get(strategy_name)
        strat_cfg = STRATEGY_CONFIG.get(strategy_name)

        # Determine strict class lookup if not in registry directly (some config keys point to same class)
        # In config_strategies.py, STRATEGY_REGISTRY keys match STRATEGY_CONFIG keys?
        # Yes, mostly.
        if not strat_cls:
            # Fallback logic if registry keys don't perfectly match config names (e.g. variants)
            # Looking at config_strategies.py, they DO match.
            return {"error": f"Strategy {strategy_name} not found in registry."}

        strategy = strat_cls(**strat_cfg) if strat_cfg else strat_cls()

        # 3. Generate Signals
        # Strategies expect 'date', 'close', etc. preprocess_gpw gives exactly that.
        try:
            df_sig = strategy.generate_signals(df)
        except Exception as e:
            return {"error": f"Strategy failed: {e}"}

        # 4. Get the LAST signal (for "tomorrow")
        last_row = df_sig.iloc[-1]

        # Convert last_row to dict to include all metrics (momentum, z-score, etc.)
        result = last_row.to_dict()
        # Ensure primitive types for JSON/usage
        result["date"] = str(result["date"])
        result["signal"] = int(result["signal"])
        result["close"] = float(result["close"])
        result["strategy"] = strategy_name
        result["params"] = str(strategy.params)

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

        # Parse Saxo NetPositions
        # Usually list under "Data"
        positions = []
        for item in raw["Data"]:
            # NetPositionBase has 'Uic', 'Amount', 'NetPositionId'
            # Sim vs Live consistency varies, but Uic/Amount usually present.
            p = {
                "uic": item.get("Uic"),
                "qty": item.get("Amount", 0),
                "id": item.get("NetPositionId"),
                "price": item.get("CurrentPrice", 0.0),
                "market_value": item.get("MarketValue", 0.0),  # E.g. Amount * CurrentPrice
            }
            positions.append(p)
        return positions
