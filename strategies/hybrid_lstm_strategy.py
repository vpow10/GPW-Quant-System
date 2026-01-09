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
class HybridLSTMRegimeBlendConfig:
    models_dir: Path = Path("models/hybrid_lstm")
    wig20_symbol: str = "wig20"

    z_entry: float = 1.0
    z_exit: float = 0.3
    min_hold_days: int = 10

    z_smooth_span: int = 10

    rebalance: str = "weekly"  # daily|weekly
    rebalance_weekday: int = 4  # 0=Mon..4=Fri

    bull_long_only: bool = True
    bear_flat: bool = True
    bear_short_only: bool = False
    normal_long_only: bool = False

    bull_vol_quantile: float = 1.0
    normal_vol_quantile: float = 0.7
    bear_vol_quantile: float = 0.7

    bull_score_blend: float = 0.6  # 0=pred_z, 1=mom_z

    universe: list[str] | None = None


class HybridLSTMRegimeBlendStrategy(StrategyBase):
    def __init__(
        self,
        *,
        name: str = "hybrid_lstm_regimeblend",
        description: str | None = None,
        universe: list[str] | None = None,
        models_dir: str | Path = "models/hybrid_lstm",
        wig20_symbol: str = "wig20",
        z_entry: float = 1.0,
        z_exit: float = 0.3,
        min_hold_days: int = 10,
        z_smooth_span: int = 10,
        rebalance: str = "weekly",
        rebalance_weekday: int = 4,
        bull_long_only: bool = True,
        bear_flat: bool = True,
        bear_short_only: bool = False,
        normal_long_only: bool = False,
        bull_vol_quantile: float = 1.0,
        normal_vol_quantile: float = 0.7,
        bear_vol_quantile: float = 0.7,
        bull_score_blend: float = 0.6,
        **_: Any,
    ) -> None:
        self.cfg = HybridLSTMRegimeBlendConfig(
            models_dir=Path(models_dir),
            wig20_symbol=wig20_symbol.lower(),
            z_entry=z_entry,
            z_exit=z_exit,
            min_hold_days=min_hold_days,
            z_smooth_span=z_smooth_span,
            rebalance=rebalance,
            rebalance_weekday=rebalance_weekday,
            bull_long_only=bull_long_only,
            bear_flat=bear_flat,
            bear_short_only=bear_short_only,
            normal_long_only=normal_long_only,
            bull_vol_quantile=bull_vol_quantile,
            normal_vol_quantile=normal_vol_quantile,
            bear_vol_quantile=bear_vol_quantile,
            bull_score_blend=bull_score_blend,
            universe=universe,
        )
        self.name = name
        self.params = asdict(self.cfg)
        self.description = description

        self._models: Dict[
            str, Tuple[RegimeGatedModel, TimeSeriesScaler, TimeSeriesScaler, TimeSeriesScaler]
        ] = {}

    def _load_for_symbol(self, sym: str):
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
                "mom_signal",
                "mr_signal",
            ]
        ].copy()
        out["hybrid_pred"] = preds
        return out

    @staticmethod
    def _zscore(s: pd.Series) -> pd.Series:
        std = s.std(ddof=0)
        if std == 0 or np.isnan(std):
            return pd.Series(0.0, index=s.index)
        return (s - s.mean()) / std

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return self._add_meta(df.assign(signal=0))

        panel = df.copy()
        if "symbol" not in panel.columns:
            raise ValueError("HybridLSTMRegimeBlendStrategy expects 'symbol' column")
        panel["symbol"] = panel["symbol"].astype(str).str.lower()

        try:
            panel = add_wig20_features(panel, wig20_symbol=self.cfg.wig20_symbol)
        except SystemExit:
            pass
        panel = merge_strategy_signals(panel)

        all_out: list[pd.DataFrame] = []
        for sym_key, g in panel.groupby("symbol", sort=False):
            sym_s = str(sym_key)
            if sym_s == self.cfg.wig20_symbol:
                continue
            out_sym = self._predict_symbol(g, sym_s)
            if not out_sym.empty:
                all_out.append(out_sym)

        if not all_out:
            return self._add_meta(df.assign(signal=0))

        sig = (
            pd.concat(all_out, ignore_index=True)
            .sort_values(["symbol", "date"])
            .reset_index(drop=True)
        )

        if self.cfg.z_smooth_span and self.cfg.z_smooth_span > 0:
            span = int(self.cfg.z_smooth_span)
            sig["hybrid_pred_s"] = sig.groupby("symbol", sort=False)["hybrid_pred"].transform(
                lambda s: s.ewm(span=span, adjust=False).mean()
            )
        else:
            sig["hybrid_pred_s"] = sig["hybrid_pred"]

        sig["pred_z"] = sig.groupby("date", sort=False)["hybrid_pred_s"].transform(self._zscore)
        sig["mom_z"] = sig.groupby("date", sort=False)["mom_signal"].transform(self._zscore)

        sig["regime"] = np.where(
            sig["wig20_mom_60d"] > 0, "BULL", np.where(sig["wig20_mom_60d"] < 0, "BEAR", "NORMAL")
        )

        vol_series = sig["wig20_vol_20d"].replace([np.inf, -np.inf], np.nan).dropna()
        if vol_series.empty:
            vol_q_bull = vol_q_norm = vol_q_bear = np.inf
        else:
            vol_q_bull = vol_series.quantile(float(self.cfg.bull_vol_quantile))
            vol_q_norm = vol_series.quantile(float(self.cfg.normal_vol_quantile))
            vol_q_bear = vol_series.quantile(float(self.cfg.bear_vol_quantile))

        w = min(1.0, max(0.0, float(self.cfg.bull_score_blend)))
        sig["score_z"] = sig["pred_z"]
        bull_mask = sig["regime"] == "BULL"
        sig.loc[bull_mask, "score_z"] = (1.0 - w) * sig.loc[bull_mask, "pred_z"] + w * sig.loc[
            bull_mask, "mom_z"
        ]

        if self.cfg.rebalance == "weekly":
            sig["rebalance"] = sig["date"].dt.weekday == int(self.cfg.rebalance_weekday)
        else:
            sig["rebalance"] = True

        z_entry = float(self.cfg.z_entry)
        z_exit = float(self.cfg.z_exit)
        min_hold = int(self.cfg.min_hold_days)

        def _symbol_signals(g: pd.DataFrame) -> pd.DataFrame:
            pos = 0
            days_in_pos = 0
            out = np.zeros(len(g), dtype=np.int8)
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
                out[i] = pos

            g["base_signal"] = out
            g["prev_signal"] = pd.Series(out, index=g.index).shift(1).fillna(0).astype(int)
            return g

        sig = pd.concat(
            [_symbol_signals(g) for _, g in sig.groupby("symbol", sort=False)], ignore_index=True
        )
        sig["signal"] = sig["base_signal"].astype(int)

        v = sig["wig20_vol_20d"].to_numpy(dtype=np.float64, copy=False)
        reg = sig["regime"].to_numpy()

        vol_ok = np.ones(len(sig), dtype=bool)
        vol_ok &= np.where(reg == "BULL", v <= vol_q_bull, True)
        vol_ok &= np.where(reg == "NORMAL", v <= vol_q_norm, True)
        vol_ok &= np.where(reg == "BEAR", v <= vol_q_bear, True)
        sig.loc[~vol_ok, "signal"] = 0

        if self.cfg.bull_long_only:
            sig.loc[sig["regime"].eq("BULL") & (sig["signal"] < 0), "signal"] = 0
        if self.cfg.normal_long_only:
            sig.loc[sig["regime"].eq("NORMAL") & (sig["signal"] < 0), "signal"] = 0
        if self.cfg.bear_flat:
            sig.loc[sig["regime"].eq("BEAR"), "signal"] = 0
        elif self.cfg.bear_short_only:
            sig.loc[sig["regime"].eq("BEAR") & (sig["signal"] > 0), "signal"] = 0

        out = df.merge(
            sig[
                [
                    "symbol",
                    "date",
                    "signal",
                    "prev_signal",
                    "hybrid_pred",
                    "hybrid_pred_s",
                    "pred_z",
                    "mom_z",
                    "score_z",
                    "regime",
                ]
            ],
            on=["symbol", "date"],
            how="left",
        )
        out["signal"] = out["signal"].fillna(0).astype(int)
        out["prev_signal"] = out["prev_signal"].fillna(0).astype(int)
        return self._add_meta(out)
