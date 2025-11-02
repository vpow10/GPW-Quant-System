from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from saxo_auth import ensure_access_token

load_dotenv()

OPENAPI_BASE: str = os.getenv(
    "SAXO_OPENAPI_BASE", "https://gateway.saxobank.com/sim/openapi"
)
ACCOUNT_KEY: Optional[str] = os.getenv("SAXO_ACCOUNT_KEY")
TIMEOUT: int = int(os.getenv("SAXO_CLIENT_TIMEOUT", "30"))

LOG_DIR = Path(os.getenv("JOURNAL_DIR", "journals"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "orders.jsonl"


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("saxo_basic")


def _headers() -> dict[str, str]:
    token = ensure_access_token()
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{OPENAPI_BASE}{path}"
    logger.debug("POST %s payload=%s", url, payload)
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(url, json=payload, headers=_headers())
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail: Any
            try:
                detail = r.json()
            except Exception:
                detail = r.text
            raise SystemExit(f"HTTP {r.status_code} POST {url} -> {detail}") from exc
        resp_json: dict[str, Any] = r.json()  # type: ignore[assignment]
        return resp_json


def log_json(obj: dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    obj_out = {"ts": datetime.utcnow().isoformat() + "Z", **obj}
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj_out, ensure_ascii=False) + "\n")
    logger.debug("Appended JSON log to %s", LOG_FILE)


def build_order_payload(
    *,
    uic: int,
    asset_type: str,
    side: str,
    amount: float,
    order_type: str,
    price: Optional[float] = None,
) -> dict[str, Any]:
    if not ACCOUNT_KEY:
        raise SystemExit("Brak SAXO_ACCOUNT_KEY w .env — wymagane do składania zleceń.")
    payload: dict[str, Any] = {
        "AccountKey": ACCOUNT_KEY,
        "Uic": uic,
        "AssetType": asset_type,  # np. "Stock", "FxSpot"
        "BuySell": side,  # "Buy" | "Sell"
        "OrderType": order_type,  # "Market" | "Limit" | ...
        "Amount": amount,  # ilość/szt./nominał
        "ManualOrder": False,
    }
    if order_type.lower() == "limit":
        if price is None:
            raise SystemExit("Dla OrderType=Limit wymagany jest --price.")
        payload["Price"] = price
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Minimalny składacz zleceń (SIM) + zapis JSON (JSONL)."
    )
    parser.add_argument("--uic", type=int, required=True, help="Instrument UIC")
    parser.add_argument("--asset-type", default="Stock", help="Np. Stock, FxSpot")
    parser.add_argument("--side", choices=["Buy", "Sell"], required=True)
    parser.add_argument("--amount", type=float, default=1.0)
    parser.add_argument("--order-type", default="Market", choices=["Market", "Limit"])
    parser.add_argument("--price", type=float, help="Cena dla zlecenia Limit")
    parser.add_argument(
        "--place",
        action="store_true",
        help="Wyślij realne zlecenie do SIM (/orders). Bez niej: /preview.",
    )
    parser.add_argument("--tag", help="Opcjonalny identyfikator/etykieta do logu")
    args = parser.parse_args()

    payload = build_order_payload(
        uic=args.uic,
        asset_type=args.asset_type,
        side=args.side,
        amount=args.amount,
        order_type=args.order_type,
        price=args.price,
    )

    path = "/trade/v2/orders" if args.place else "/trade/v2/orders/preview"
    resp = api_post(path, payload)

    mode = "PLACE" if args.place else "PREVIEW"
    logger.info("[%s] OK. Pola odpowiedzi: %s", mode, list(resp.keys())[:8])

    log_json(
        {
            "mode": mode,
            "uic": args.uic,
            "asset_type": args.asset_type,
            "side": args.side,
            "amount": args.amount,
            "order_type": args.order_type,
            "price": args.price,
            "payload": payload,
            "response": resp,
            "tag": args.tag,
        }
    )


if __name__ == "__main__":
    main()
