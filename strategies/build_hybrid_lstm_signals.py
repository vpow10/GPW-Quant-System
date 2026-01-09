# noqa: T201
"""
Build hybrid LSTM signals with regime-dependent portfolio logic.

Example:
  python build_hybrid_lstm_signals_regimeblend.py \
    --output data/signals/hybrid_regimeblend.parquet \
    --z-entry 1.0 --z-exit 0.3 --min-hold-days 10 \
    --bull-long-only \
    --bear-flat \
    --bull-score-blend 0.6 \
    --z-smooth-span 10 \
    --rebalance weekly --rebalance-weekday 4 \
    --bull-vol-quantile 1.0 --normal-vol-quantile 0.7
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from strategies.hybrid_features import (
    REGIME_FEATURES,
    SEQ_GROUPS,
    TAB_FEATURES,
    TARGET,
    add_stock_indicators,
    add_wig20_features,
    build_seq_array,
    merge_strategy_signals,
)
from strategies.lstm_utils import TimeSeriesScaler
from strategies.NNmodels import HybridLSTM, RegimeGatedModel

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = REPO_ROOT / "data" / "processed" / "reports" / "combined.parquet"
MODELS_DIR = REPO_ROOT / "models" / "hybrid_lstm"

SYMBOLS = [
    "acp",
    "bhw",
    "brs",
    "gtc",
    "jsw",
    "ker",
    "kgh",
    "lwb",
    "peo",
    "pge",
    "pkn",
    "pko",
    "pzu",
    "tpe",
]

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def load_model_for_symbol(sym: str):
    ckpt_path = MODELS_DIR / f"{sym}_hybrid_lstm.pth"
    if not ckpt_path.exists():
        return None, None, None, None

    ckpt = torch.load(ckpt_path, map_location=DEVICE)

    core = HybridLSTM(
        seq_input_size=ckpt["seq_input_size"],
        tab_input_size=ckpt["tab_input_size"],
        lstm_hidden=ckpt["lstm_hidden"],
        lstm_layers=ckpt["lstm_layers"],
        tab_hidden=ckpt["tab_hidden"],
        head_hidden=ckpt["head_hidden"],
        dropout=ckpt["dropout"],
    )
    model = RegimeGatedModel(
        base_model=core,
        regime_input_size=ckpt["regime_input_size"],
        regime_hidden=ckpt["regime_hidden"],
    ).to(DEVICE)

    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()

    seq_scaler = TimeSeriesScaler()
    tab_scaler = TimeSeriesScaler()
    reg_scaler = TimeSeriesScaler()

    seq_scaler.load(str(MODELS_DIR / f"{sym}_seq_scaler.json"))
    tab_scaler.load(str(MODELS_DIR / f"{sym}_tab_scaler.json"))
    reg_scaler.load(str(MODELS_DIR / f"{sym}_reg_scaler.json"))

    return model, seq_scaler, tab_scaler, reg_scaler


def generate_predictions_for_symbol(df_sym: pd.DataFrame, sym: str) -> pd.DataFrame:
    model, seq_scaler, tab_scaler, reg_scaler = load_model_for_symbol(sym)
    if model is None:
        print(f"[{sym}] no model, skipping")
        return pd.DataFrame()

    df_sym = add_stock_indicators(df_sym)

    all_seq_cols = [c for group in SEQ_GROUPS for c in group]
    all_req = all_seq_cols + TAB_FEATURES + REGIME_FEATURES + [TARGET]

    df_sym = df_sym.dropna(subset=all_req).sort_values("date")
    if df_sym.empty:
        print(f"[{sym}] no rows after dropna, skipping")
        return pd.DataFrame()

    seq_array = build_seq_array(df_sym)
    tab_array = df_sym[TAB_FEATURES].to_numpy(dtype=np.float32)
    reg_array = df_sym[REGIME_FEATURES].to_numpy(dtype=np.float32)

    seq_flat = seq_array.reshape(seq_array.shape[0], -1)
    seq_scaled = seq_scaler.transform(seq_flat).reshape(seq_array.shape)
    tab_scaled = tab_scaler.transform(tab_array)
    reg_scaled = reg_scaler.transform(reg_array)

    X_seq = torch.tensor(seq_scaled, dtype=torch.float32, device=DEVICE)
    X_tab = torch.tensor(tab_scaled, dtype=torch.float32, device=DEVICE)
    X_reg = torch.tensor(reg_scaled, dtype=torch.float32, device=DEVICE)

    with torch.no_grad():
        preds = model(X_seq, X_tab, X_reg).cpu().numpy().flatten()

    out = df_sym[
        [
            "symbol",
            "date",
            "close",
            "ret_1d",
            "volume",
            "wig20_mom_60d",
            "wig20_vol_20d",
            "wig20_rsi_14",
            "mom_signal",
            "mr_signal",
        ]
    ].copy()
    out["hybrid_pred"] = preds
    return out


def _zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build hybrid LSTM signals parquet (RegimeBlend)."
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Output Parquet path for signals."
    )
    parser.add_argument("--z-entry", type=float, default=1.0)
    parser.add_argument("--z-exit", type=float, default=0.3)
    parser.add_argument("--min-hold-days", type=int, default=10)

    parser.add_argument(
        "--z-smooth-span",
        type=int,
        default=10,
        help="EWMA span on hybrid_pred per symbol (0 disables).",
    )

    parser.add_argument("--rebalance", choices=["daily", "weekly"], default="weekly")
    parser.add_argument(
        "--rebalance-weekday",
        type=int,
        default=4,
        help="0=Mon ... 4=Fri (used if rebalance=weekly).",
    )

    parser.add_argument(
        "--bull-long-only", action="store_true", help="Disable shorts in bull regime."
    )
    parser.add_argument(
        "--bear-flat", action="store_true", help="Set all signals to 0 in bear regime."
    )
    parser.add_argument(
        "--bear-short-only",
        action="store_true",
        help="Only allow shorts in bear regime (ignored if --bear-flat).",
    )
    parser.add_argument(
        "--normal-long-only", action="store_true", help="Disable shorts in normal regime."
    )

    parser.add_argument(
        "--bull-vol-quantile",
        type=float,
        default=1.0,
        help="Vol quantile threshold in bull (1.0 disables vol filter).",
    )
    parser.add_argument(
        "--normal-vol-quantile", type=float, default=0.7, help="Vol quantile threshold in normal."
    )
    parser.add_argument(
        "--bear-vol-quantile",
        type=float,
        default=0.7,
        help="Vol quantile threshold in bear (used only if not flat).",
    )

    parser.add_argument(
        "--bull-score-blend",
        type=float,
        default=0.6,
        help="0=pred_z only; 1=mom_z only (in bull).",
    )

    args = parser.parse_args()

    if not DATA_PATH.exists():
        raise SystemExit(f"Missing combined panel at {DATA_PATH}")

    if args.bear_flat and args.bear_short_only:
        print("[warn] --bear-flat overrides --bear-short-only.")

    panel = pd.read_parquet(DATA_PATH)
    panel = panel.loc[:, ~panel.columns.str.contains("^Unnamed")]
    panel["date"] = pd.to_datetime(panel["date"])
    panel["symbol"] = panel["symbol"].astype(str).str.lower()

    panel = add_wig20_features(panel)
    panel = merge_strategy_signals(panel)

    all_out = []
    for sym in SYMBOLS:
        df_sym = panel[panel["symbol"] == sym].copy()
        if df_sym.empty:
            print(f"[{sym}] no data in panel")
            continue
        out = generate_predictions_for_symbol(df_sym, sym)
        if not out.empty:
            all_out.append(out)

    if not all_out:
        raise SystemExit("No predictions produced.")

    signals = (
        pd.concat(all_out, ignore_index=True)
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )

    if args.z_smooth_span and args.z_smooth_span > 0:
        span = int(args.z_smooth_span)
        signals["hybrid_pred_s"] = signals.groupby("symbol", sort=False)["hybrid_pred"].transform(
            lambda s: s.ewm(span=span, adjust=False).mean()
        )
    else:
        signals["hybrid_pred_s"] = signals["hybrid_pred"]

    signals["pred_z"] = signals.groupby("date", sort=False)["hybrid_pred_s"].transform(_zscore)
    signals["mom_z"] = signals.groupby("date", sort=False)["mom_signal"].transform(_zscore)

    signals["regime"] = np.where(
        signals["wig20_mom_60d"] > 0,
        "BULL",
        np.where(signals["wig20_mom_60d"] < 0, "BEAR", "NORMAL"),
    )

    vol_series = signals["wig20_vol_20d"].replace([np.inf, -np.inf], np.nan).dropna()
    if vol_series.empty:
        vol_q_bull = vol_q_norm = vol_q_bear = np.inf
    else:
        vol_q_bull = vol_series.quantile(float(args.bull_vol_quantile))
        vol_q_norm = vol_series.quantile(float(args.normal_vol_quantile))
        vol_q_bear = vol_series.quantile(float(args.bear_vol_quantile))

    w = min(1.0, max(0.0, float(args.bull_score_blend)))
    signals["score_z"] = signals["pred_z"]
    bull_mask = signals["regime"] == "BULL"
    signals.loc[bull_mask, "score_z"] = (1.0 - w) * signals.loc[
        bull_mask, "pred_z"
    ] + w * signals.loc[bull_mask, "mom_z"]

    z_entry = float(args.z_entry)
    z_exit = float(args.z_exit)
    min_hold = int(args.min_hold_days)

    if args.rebalance == "weekly":
        signals["rebalance"] = signals["date"].dt.weekday == int(args.rebalance_weekday)
    else:
        signals["rebalance"] = True

    def _symbol_signals(g: pd.DataFrame) -> pd.DataFrame:
        pos = 0
        days_in_pos = 0
        sig = np.zeros(len(g), dtype=np.int8)

        z_vals = g["score_z"].to_numpy(dtype=np.float64, copy=False)
        reb = g["rebalance"].to_numpy(dtype=bool, copy=False)

        for i, z in enumerate(z_vals):
            if pos == 0:
                days_in_pos = 0
                if reb[i]:
                    if z > z_entry:
                        pos = 1
                        days_in_pos = 1
                    elif z < -z_entry:
                        pos = -1
                        days_in_pos = 1
            else:
                days_in_pos += 1
                if reb[i] and days_in_pos >= min_hold:
                    if pos == 1 and z < z_exit:
                        pos = 0
                        days_in_pos = 0
                    elif pos == -1 and z > -z_exit:
                        pos = 0
                        days_in_pos = 0
            sig[i] = pos

        g["base_signal"] = sig
        g["prev_signal"] = pd.Series(sig, index=g.index).shift(1).fillna(0).astype(int)
        return g

    signals = pd.concat(
        [_symbol_signals(g) for _, g in signals.groupby("symbol", sort=False)], ignore_index=True
    )

    signals["signal"] = signals["base_signal"].astype(int)

    v = signals["wig20_vol_20d"].to_numpy(dtype=np.float64, copy=False)
    reg = signals["regime"].to_numpy()

    vol_ok = np.ones(len(signals), dtype=bool)
    vol_ok &= np.where(reg == "BULL", v <= vol_q_bull, True)
    vol_ok &= np.where(reg == "NORMAL", v <= vol_q_norm, True)
    vol_ok &= np.where(reg == "BEAR", v <= vol_q_bear, True)
    signals.loc[~vol_ok, "signal"] = 0

    if args.bull_long_only:
        signals.loc[signals["regime"].eq("BULL") & (signals["signal"] < 0), "signal"] = 0

    if args.normal_long_only:
        signals.loc[signals["regime"].eq("NORMAL") & (signals["signal"] < 0), "signal"] = 0

    if args.bear_flat:
        signals.loc[signals["regime"].eq("BEAR"), "signal"] = 0
    elif args.bear_short_only:
        signals.loc[signals["regime"].eq("BEAR") & (signals["signal"] > 0), "signal"] = 0

    signals["signal"] = signals["signal"].astype(int)
    signals["prev_signal"] = signals["prev_signal"].astype(int)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    signals.to_parquet(args.output, index=False)
    print(f"Saved hybrid signals to {args.output}")


if __name__ == "__main__":
    main()
