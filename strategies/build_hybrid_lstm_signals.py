# noqa: T201
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


def apply_hysteresis(
    preds: np.ndarray, threshold: float, exit_threshold: float | None
) -> np.ndarray:
    if exit_threshold is None:
        exit_threshold = threshold * 0.5

    current_pos = 0
    sigs = np.zeros_like(preds)
    for i, p in enumerate(preds):
        if current_pos == 0:
            if p > threshold:
                current_pos = 1
            elif p < -threshold:
                current_pos = -1
        elif current_pos == 1:
            if p < exit_threshold:
                current_pos = 0
        elif current_pos == -1:
            if p > -exit_threshold:
                current_pos = 0
        sigs[i] = current_pos
    return sigs


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
        ]
    ].copy()
    out["hybrid_pred"] = preds
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Build hybrid LSTM signals parquet.")
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output Parquet path for signals.",
    )
    # hysteresis and regime params to tune
    parser.add_argument("--z-entry", type=float, default=1.0)
    parser.add_argument("--z-exit", type=float, default=0.3)
    parser.add_argument("--vol-quantile", type=float, default=0.8)
    parser.add_argument("--min-hold-days", type=int, default=5)
    args = parser.parse_args()

    if not DATA_PATH.exists():
        raise SystemExit(f"Missing combined panel at {DATA_PATH}")

    panel = pd.read_parquet(DATA_PATH)
    panel = panel.loc[:, ~panel.columns.str.contains("^Unnamed")]
    panel["date"] = pd.to_datetime(panel["date"])
    panel["symbol"] = panel["symbol"].str.lower()

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

    signals = pd.concat(all_out, ignore_index=True)

    # 1) cross-sectional z-score of predictions per day
    def _zscore(s: pd.Series) -> pd.Series:
        std = s.std(ddof=0)
        if std == 0 or np.isnan(std):
            return pd.Series(0.0, index=s.index)
        return (s - s.mean()) / std

    signals["pred_z"] = signals.groupby("date")["hybrid_pred"].transform(_zscore)

    # 2) per-symbol hysteresis + min holding
    signals = signals.sort_values(["symbol", "date"]).reset_index(drop=True)

    z_entry = args.z_entry
    z_exit = args.z_exit
    min_hold = args.min_hold_days

    def _symbol_signals(g: pd.DataFrame) -> pd.DataFrame:
        pos = 0
        days_in_pos = 0
        sig = np.zeros(len(g), dtype=np.int8)
        z_vals = g["pred_z"].to_numpy()

        for i, z in enumerate(z_vals):
            if pos == 0:
                days_in_pos = 0
                if z > z_entry:
                    pos = 1
                    days_in_pos = 1
                elif z < -z_entry:
                    pos = -1
                    days_in_pos = 1
            else:
                days_in_pos += 1
                if days_in_pos >= min_hold:
                    if pos == 1 and z < z_exit:
                        pos = 0
                        days_in_pos = 0
                    elif pos == -1 and z > -z_exit:
                        pos = 0
                        days_in_pos = 0
            sig[i] = pos

        g["base_signal"] = sig
        return g

    groups = []
    for _, g in signals.groupby("symbol", sort=False):
        groups.append(_symbol_signals(g))
    signals = pd.concat(groups, ignore_index=True)

    # 3) WIG20 regime filter
    vol_q = signals["wig20_vol_20d"].quantile(args.vol_quantile)
    regime_good = (signals["wig20_mom_60d"] > 0) & (signals["wig20_vol_20d"] <= vol_q)

    signals["signal"] = 0
    signals.loc[regime_good, "signal"] = signals.loc[regime_good, "base_signal"]

    signals.to_parquet(args.output, index=False)
    print(f"Saved hybrid LSTM signals to {args.output}")


if __name__ == "__main__":
    main()
