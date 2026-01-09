from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, cast

import httpx
from dotenv import load_dotenv

from .saxo_auth import ensure_access_token

load_dotenv()


class SaxoClient:
    """Minimalny klient do składania / podglądu zleceń (SIM) + log JSONL."""

    def __init__(
        self,
        *,
        openapi_base: str,
        account_key: str,
        timeout: int = 30,
        log_file: Path | str = Path(os.getenv("JOURNAL_DIR", "journals")) / "orders.jsonl",
    ) -> None:
        self.openapi_base = openapi_base.rstrip("/")
        self.account_key = account_key
        self.timeout = timeout
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    # ---- fabryka z ENV ----
    @classmethod
    def from_env(cls) -> "SaxoClient":
        openapi_base: str = os.getenv(
            "SAXO_OPENAPI_BASE", "https://gateway.saxobank.com/sim/openapi"
        ).strip()
        account_key: Optional[str] = os.getenv("SAXO_ACCOUNT_KEY")
        if account_key:
            account_key = account_key.strip()
        if not account_key:
            raise SystemExit("Brak SAXO_ACCOUNT_KEY w .env — wymagane do składania zleceń.")
        timeout: int = int(os.getenv("SAXO_CLIENT_TIMEOUT", "30"))
        journal_dir = Path(os.getenv("JOURNAL_DIR", "journals"))
        return cls(
            openapi_base=openapi_base,
            account_key=account_key,
            timeout=timeout,
            log_file=journal_dir / "orders.jsonl",
        )

    @classmethod
    def _headers(cls) -> dict[str, str]:
        token = ensure_access_token()
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    def api_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.openapi_base}{path}"
        import time

        for attempt in range(5):
            with httpx.Client(timeout=self.timeout) as client:
                r = client.post(url, json=payload, headers=self._headers())

                if r.status_code == 429:
                    wait_sec = int(r.headers.get("Retry-After", 2 ** (attempt + 1)))
                    print(f"[API] Rate limit 429 hit. Sleeping {wait_sec}s...")
                    time.sleep(wait_sec)
                    continue

                try:
                    r.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    ctype = r.headers.get("content-type", "")
                    req_id = r.headers.get("X-Request-Id") or r.headers.get("Request-Id")
                    try:
                        detail: Any = r.json()
                    except Exception:
                        detail = r.text or repr(r.content)
                    if r.status_code == 429:
                        time.sleep(2)
                        continue

                    raise SystemExit(
                        "Order POST failed.\n"
                        f"  url         : {url}\n"
                        f"  status      : {r.status_code}\n"
                        f"  content-type: {ctype}\n"
                        f"  request-id  : {req_id}\n"
                        f"  response    : {detail}"
                    ) from exc

                resp_json: dict[str, Any] = r.json()  # type: ignore[assignment]
                return resp_json

        raise SystemExit(f"API failed after max retries: {url}")

    def log_json(self, obj: dict[str, Any]) -> None:
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        obj_out = {"ts": datetime.utcnow().isoformat() + "Z", **obj}
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj_out, ensure_ascii=False) + "\n")

    def build_order_payload(
        self,
        *,
        uic: int,
        asset_type: str,
        side: str,
        amount: float,
        order_type: str,
        price: Optional[float] = None,
        client_order_id: Optional[str] = None,
        manual_order: bool = False,
    ) -> dict[str, Any]:
        if not self.account_key:
            raise SystemExit("Brak SAXO_ACCOUNT_KEY w .env — wymagane do składania zleceń.")

        payload: dict[str, Any] = {
            "AccountKey": self.account_key,
            "Uic": uic,
            "AssetType": asset_type,
            "BuySell": side,
            "OrderType": order_type,
            "Amount": amount,
            "ManualOrder": manual_order,
            "ClientOrderId": client_order_id or str(uuid.uuid4()),
        }

        if order_type.lower() != "market":
            if price is None:
                raise SystemExit("Dla OrderType≠Market wymagany jest price (OrderPrice).")
            payload["OrderPrice"] = price

        return payload

    def preview_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.api_post("/trade/v2/orders/precheck", payload)

    def place_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self.api_post("/trade/v2/orders", payload)
        self.log_json({"request": payload, "response": resp})
        return resp

    def get_net_positions(self) -> dict[str, Any]:
        """Pobiera otwarte pozycje (NetPositions)."""
        url = f"{self.openapi_base}/port/v1/netpositions/me"
        with httpx.Client(timeout=self.timeout) as c:
            r = c.get(url, headers=self._headers())
            if r.status_code == 200:
                return cast("dict[str, Any]", r.json())
            return {"error": f"HTTP {r.status_code}", "raw": r.text}
