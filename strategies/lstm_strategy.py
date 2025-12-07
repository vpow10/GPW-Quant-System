import os
import numpy as np
import pandas as pd
import torch
import polars as pl # Optional, but typical in this repo? Base uses pandas.

from strategies.base import StrategyBase
from strategies.lstm_utils import LSTMModel, TimeSeriesScaler

class LSTMStrategy(StrategyBase):
    def __init__(self, models_dir: str = "./models", threshold: float = 0.0, smoothing_window: int = 1, exit_threshold: float = None, **kwargs):
        self.models_dir = models_dir
        self.threshold = threshold
        self.smoothing_window = smoothing_window
        self.exit_threshold = exit_threshold
        self.params = {
            "models_dir": models_dir,
            "threshold": threshold,
            "smoothing_window": smoothing_window,
            "exit_threshold": exit_threshold,
            **kwargs,
        }
        self.name = "lstm"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        # Expects dataframe with at least symbol, close, ret_1d, volume
        models_dir = self.models_dir
        threshold = self.threshold
        smoothing_window = self.smoothing_window
        exit_threshold = self.exit_threshold
        
        # We need to process per symbol
        df_out = df.copy()
        df_out["signal"] = 0
        df_out["lstm_pred"] = np.nan
        
        # Features calculation needs to be identical to training
        # We can try to infer features from the first model we load or hardcode?
        # Ideally load from model.
        
        # Group by symbol
        symbols = df["symbol"].unique()
        
        for sym in symbols:
            model_path = os.path.join(models_dir, f"{sym}_lstm.pth")
            scaler_path = os.path.join(models_dir, f"{sym}_scaler.json")
            
            if not os.path.exists(model_path) or not os.path.exists(scaler_path):
                # print(f"Output for {sym} skipped (no model)")
                continue
                
            # Load metadata
            checkpoint = torch.load(model_path)
            seq_len = checkpoint["seq_len"]
            input_size = checkpoint["input_size"]
            features_list = checkpoint["features"]
            hidden_size = checkpoint["hidden_size"]
            num_layers = checkpoint["num_layers"]
            
            # Load Scaler
            scaler = TimeSeriesScaler()
            scaler.load(scaler_path)
            
            # Load Model
            model = LSTMModel(input_size, hidden_size, num_layers)
            model.load_state_dict(checkpoint["model_state_dict"])
            model.eval()
            
            # Prepare Data for this symbol
            # We must apply the same transformations
            mask = df["symbol"] == sym
            sub_df = df.loc[mask].sort_values("date").copy()
            
            # Feature Eng (must match train_lstm.py)
            sub_df["ret_1d_log"] = np.log1p(sub_df["ret_1d"])
            sub_df["volume"] = sub_df["volume"].replace(0, 1)
            sub_df["vol_log"] = np.log(sub_df["volume"])
            sub_df["vol_log_chg"] = sub_df["vol_log"].diff()
            
            # Create Lags
            # We need to loop because features_list names like "log_return_lag1"
            # It's better to just re-create them structurally
            # We assume features_list matches the order we create:
            # log_return_lag1..N, log_vol_chg_lag1..N
            
            # Determine MAX lag from features to know how much we lose
            # Or just recreate based on names
            for feat in features_list:
                if feat in sub_df.columns: continue
                # Parse: log_return_lagX
                if "log_return_lag" in feat:
                    lag = int(feat.replace("log_return_lag", ""))
                    sub_df[feat] = sub_df["ret_1d_log"].shift(lag)
                elif "log_vol_chg_lag" in feat:
                    lag = int(feat.replace("log_vol_chg_lag", ""))
                    sub_df[feat] = sub_df["vol_log_chg"].shift(lag)
            
            # Now select X
            # We need to fill NaNs or drop them. 
            # In inference, if we drop, we can't predict for the first N days. That's fine.
            valid_indices = sub_df.dropna(subset=features_list).index
            
            if len(valid_indices) == 0:
                continue
                
            X_data = sub_df.loc[valid_indices, features_list].to_numpy() # (N, features_flat)
            
            # Scale
            X_scaled = scaler.transform(X_data)
            
            # Reshape (N, seq_len, input_size)
            # SAME LOGIC AS TRAIN
            N = X_scaled.shape[0]
            # Assumes first half is ret, second half is vol
            # We need to be careful if FEATURES list is interleaved.
            # train_lstm.py: feat = [all ret lags] + [all vol lags]
            # So first SEQ_LEN cols are ret, next SEQ_LEN are vol.
            
            X_reshaped = np.zeros((N, seq_len, input_size))
            X_reshaped[:, :, 0] = X_scaled[:, :seq_len]
            X_reshaped[:, :, 1] = X_scaled[:, seq_len:]
            
            # Inference
            X_tensor = torch.tensor(X_reshaped, dtype=torch.float32)
            with torch.no_grad():
                # Model returns (N, 1)
                preds = model(X_tensor).numpy().flatten()
                
            # Smoothing
            if smoothing_window > 1:
                s_preds = pd.Series(preds, index=valid_indices)
                s_smooth = s_preds.rolling(window=smoothing_window).mean()
                preds_to_use = s_smooth.fillna(0).values
                df_out.loc[valid_indices, "lstm_pred"] = preds_to_use
            else:
                preds_to_use = preds
            
            # Hysteresis Logic
            # We must iterate to maintain state
            # current_pos: 0=flat, 1=long, -1=short
            current_pos = 0
            sigs = np.zeros(len(preds_to_use))
            
            # Define thresholds
            entry_thresh = threshold
            # Exit threshold
            exit_thresh = exit_threshold if exit_threshold is not None else threshold * 0.5
            
            for i, p in enumerate(preds_to_use):
                if current_pos == 0:
                    if p > entry_thresh:
                        current_pos = 1
                    elif p < -entry_thresh:
                        current_pos = -1
                elif current_pos == 1:
                    # Exit if prediction drops below exit_thresh
                    if p < exit_thresh:
                        current_pos = 0
                elif current_pos == -1:
                    # Exit if prediction rises above -exit_thresh
                    if p > -exit_thresh:
                        current_pos = 0
                
                sigs[i] = current_pos
                
            df_out.loc[valid_indices, "signal"] = sigs

        # Fill NaNs in signal with 0
        df_out["signal"] = df_out["signal"].fillna(0)
        return df_out
