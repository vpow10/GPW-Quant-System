from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
import torch

from strategies.base import StrategyBase
from strategies.hybrid_features import (
    REGIME_FEATURES,
    SEQ_GROUPS,
    TAB_FEATURES,
    add_stock_indicators,
    add_wig20_features,
    build_seq_array,
    merge_strategy_signals,
)
from strategies.lstm_utils import TimeSeriesScaler
from strategies.NNmodels import HybridLSTM, RegimeGatedModel

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


@dataclass
class HybridLSTMConfig:
    models_dir: Path = Path("models/hybrid_lstm")

    wig20_symbol: str = "wig20"

    z_entry: float = 1.0
    z_exit: float = 0.3
    vol_quantile: float = 0.7
    min_hold_days: int = 5

    long_only: bool = False

    universe: list[str] | None = None


class HybridLSTMStrategy(StrategyBase):
    """
    Strategy wrapper around the hybrid LSTM models.

    It:
      - loads per-symbol hybrid LSTM + scalers from disk
      - recomputes features on the incoming panel
      - generates cross-sectional z-scored predictions
      - applies hysteresis + min holding + WIG20 regime filter
      - returns df with 'signal' + metadata
    """

    def __init__(
        self,
        *,
        name: str = "hybrid_lstm_10d",
        description: str | None = None,
        universe: list[str] | None = None,
        long_only: bool = False,
        models_dir: str | Path = "models/hybrid_lstm",
        z_entry: float = 1.0,
        z_exit: float = 0.3,
        vol_quantile: float = 0.7,
        min_hold_days: int = 5,
        wig20_symbol: str = "wig20",
        **_: Any,
    ) -> None:
        self.cfg = HybridLSTMConfig(
            models_dir=Path(models_dir),
            wig20_symbol=wig20_symbol.lower(),
            z_entry=z_entry,
            z_exit=z_exit,
            vol_quantile=vol_quantile,
            min_hold_days=min_hold_days,
            long_only=long_only,
            universe=universe,
        )
        self.name = name
        self.params = asdict(self.cfg)

        # cache models per symbol so we don’t reload on every call
        self._models: Dict[
            str, Tuple[RegimeGatedModel, TimeSeriesScaler, TimeSeriesScaler, TimeSeriesScaler]
        ] = {}

    # ---------- internal helpers ----------

    def _load_for_symbol(
        self, sym: str
    ) -> Tuple[RegimeGatedModel, TimeSeriesScaler, TimeSeriesScaler, TimeSeriesScaler]:
        sym = sym.lower()
        if sym in self._models:
            return self._models[sym]

        ckpt_path = self.cfg.models_dir / f"{sym}_hybrid_lstm.pth"
        if not ckpt_path.exists():
            raise FileNotFoundError(f"No LSTM checkpoint for symbol={sym} at {ckpt_path}")

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

        seq_scaler.load(str(self.cfg.models_dir / f"{sym}_seq_scaler.json"))
        tab_scaler.load(str(self.cfg.models_dir / f"{sym}_tab_scaler.json"))
        reg_scaler.load(str(self.cfg.models_dir / f"{sym}_reg_scaler.json"))

        self._models[sym] = (model, seq_scaler, tab_scaler, reg_scaler)
        return self._models[sym]

    def _predict_symbol(self, df_sym: pd.DataFrame, sym: str) -> pd.DataFrame:
        model, seq_scaler, tab_scaler, reg_scaler = self._load_for_symbol(sym)

        df_sym = add_stock_indicators(df_sym)

        # --- intraday safety: ensure all required “macro / aux” columns exist ---
        # For intraday we don’t have daily WIG20 or cross-strategy signals available,
        # so we fall back to zeros instead of crashing on missing columns.
        required_extra = [
            "wig20_ret_1d",
            "wig20_mom_60d",
            "wig20_vol_20d",
            "wig20_rsi_14",
            "beta_60d",
            "mom_signal",
            "mr_signal",
        ]
        for c in required_extra:
            if c not in df_sym.columns:
                df_sym[c] = 0.0
            else:
                df_sym[c] = df_sym[c].fillna(0.0)

        all_seq_cols = [c for group in SEQ_GROUPS for c in group]
        all_req = all_seq_cols + TAB_FEATURES + REGIME_FEATURES

        df_sym = df_sym.dropna(subset=all_req).sort_values("date")
        if df_sym.empty:
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

    # ---------- public API ----------

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return self._add_meta(df.assign(signal=0))

        panel = df.copy()

        if "symbol" not in panel.columns:
            raise ValueError("HybridLSTMStrategy expects 'symbol' column")

        panel["symbol"] = panel["symbol"].astype(str).str.lower()

        # ---------- SINGLE-SYMBOL / LIVE (incl. intraday) ----------
        if panel["symbol"].nunique() == 1:
            sym = str(panel["symbol"].iloc[0])
            out_sym = self._predict_symbol(panel, sym)

            if out_sym.empty:
                out = panel.assign(signal=0)
            else:
                # simple per-symbol rule: sign of hybrid_pred
                preds = out_sym["hybrid_pred"].to_numpy(dtype=np.float64, copy=False)
                thr: float = 0.0

                sig = np.zeros(preds.shape[0], dtype=np.int8)
                sig[preds > thr] = 1
                if not self.cfg.long_only:
                    sig[preds < -thr] = -1

                out_sym["signal"] = sig

                # merge signals back onto original df by date
                out = panel.merge(
                    out_sym[["date", "hybrid_pred", "signal"]],
                    on="date",
                    how="left",
                )
                out["hybrid_pred"] = out["hybrid_pred"].astype(float)
                out["signal"] = out["signal"].fillna(0).astype(int)

            # add prev_signal so trader can detect changes
            out = out.sort_values("date")
            out["prev_signal"] = out["signal"].shift(1).fillna(0).astype(int)
            return self._add_meta(out)

        # ---------- MULTI-SYMBOL / OFFLINE RESEARCH (original logic) ----------

        try:
            panel = add_wig20_features(panel, wig20_symbol=self.cfg.wig20_symbol)
        except SystemExit:
            # if no wig20 in panel, just continue without it
            pass

        panel = merge_strategy_signals(panel)

        all_out: list[pd.DataFrame] = []
        for sym_key, g in panel.groupby("symbol", sort=False):
            sym_s: str = str(sym_key)
            if sym_s == self.cfg.wig20_symbol:
                continue
            out_sym = self._predict_symbol(g, sym_s)
            if not out_sym.empty:
                all_out.append(out_sym)

        if not all_out:
            return self._add_meta(df.assign(signal=0))

        signals = pd.concat(all_out, ignore_index=True)

        # 1) cross-sectional z-score per day
        def _zscore(s: pd.Series) -> pd.Series:
            std = s.std(ddof=0)
            if std == 0 or np.isnan(std):
                return pd.Series(0.0, index=s.index)
            return (s - s.mean()) / std

        signals["pred_z"] = signals.groupby("date")["hybrid_pred"].transform(_zscore)

        # 2) hysteresis + min holding per symbol
        signals = signals.sort_values(["symbol", "date"]).reset_index(drop=True)

        z_entry = self.cfg.z_entry
        z_exit = self.cfg.z_exit
        min_hold = self.cfg.min_hold_days
        long_only = self.cfg.long_only

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
                    elif z < -z_entry and not long_only:
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

            g["signal"] = sig
            g["prev_signal"] = g["signal"].shift(1).fillna(0).astype(int)
            return g

        groups = []
        for _, g in signals.groupby("symbol", sort=False):
            groups.append(_symbol_signals(g))
        signals = pd.concat(groups, ignore_index=True)

        # 3) WIG20 regime filter (only if we actually have these columns)
        if "wig20_vol_20d" in signals.columns and "wig20_mom_60d" in signals.columns:
            vol_q = signals["wig20_vol_20d"].quantile(self.cfg.vol_quantile)
            regime_good = (signals["wig20_mom_60d"] > 0) & (signals["wig20_vol_20d"] <= vol_q)
            signals.loc[~regime_good, "signal"] = 0

        out = df.merge(
            signals[["symbol", "date", "signal", "prev_signal", "hybrid_pred", "pred_z"]],
            on=["symbol", "date"],
            how="left",
        )
        out["signal"] = out["signal"].fillna(0).astype(int)
        out["prev_signal"] = out["prev_signal"].fillna(0).astype(int)
        out["hybrid_pred"] = out["hybrid_pred"].astype(float)
        out["pred_z"] = out["pred_z"].astype(float)
        return self._add_meta(out)
