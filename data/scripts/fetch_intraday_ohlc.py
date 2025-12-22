from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

import pandas as pd

from data.scripts.saxo_probe import api_get


@dataclass
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None


def _to_float(x: Any) -> float:
    if x is None:
        return 0.0
    return float(x)


def fetch_recent_bars(
    uic: int,
    asset_type: str = "Stock",
    horizon_min: int = 60,
    count: int = 50,
) -> list[Bar]:
    params = {
        "Uic": uic,
        "AssetType": asset_type,
        "Horizon": horizon_min,
        "Count": count,
        "FieldGroups": "Data,DisplayAndFormat",
    }
    data = api_get("/chart/v3/charts", params)
    rows: List[Dict[str, Any]] = data.get("Data", [])

    bars: list[Bar] = []
    for row in rows:
        t = datetime.fromisoformat(row["Time"].replace("Z", "+00:00")).astimezone(timezone.utc)
        vol_raw = row.get("Volume")
        volume = float(vol_raw) if vol_raw is not None else None
        bars.append(
            Bar(
                time=t,
                open=_to_float(row.get("Open")),
                high=_to_float(row.get("High")),
                low=_to_float(row.get("Low")),
                close=_to_float(row.get("Close")),
                volume=volume,
            )
        )
    return bars


def last_bar_to_df(
    uic: int,
    symbol: str,
    asset_type: str = "Stock",
    horizon_min: int = 60,
) -> pd.DataFrame:
    bars = fetch_recent_bars(uic=uic, asset_type=asset_type, horizon_min=horizon_min, count=1)
    if not bars:
        raise RuntimeError(f"No bars returned for UIC={uic}")
    bar = bars[-1]
    df = pd.DataFrame(
        {
            "symbol": [symbol.lower()],
            "timestamp": [bar.time],
            "close": [bar.close],
            "open": [bar.open],
            "high": [bar.high],
            "low": [bar.low],
            "volume": [bar.volume if bar.volume is not None else 0.0],
        }
    )
    return df
