# noqa: T201
import os
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset

from strategies.hybrid_features import (
    LAGS,
    REGIME_FEATURES,
    SEQ_GROUPS,
    SEQ_INPUT_SIZE,
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
MOMENTUM_PATH = REPO_ROOT / "data" / "signals" / "momentum.parquet"
MEANREV_PATH = REPO_ROOT / "data" / "signals" / "mean_reversion.parquet"

MODELS_DIR = REPO_ROOT / "models" / "hybrid_lstm"
os.makedirs(MODELS_DIR, exist_ok=True)

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

TEST_SIZE = 0.20
VAL_SIZE = 0.15

NUM_EPOCHS = 400
PATIENCE = 40
BATCH_SIZE = 64
LEARNING_RATE = 1e-3


LSTM_HIDDEN = 64
LSTM_LAYERS = 1
TAB_HIDDEN = 32
HEAD_HIDDEN = 64
REGIME_HIDDEN = 16
DROPOUT = 0.2
TRAIN_END_DATE = pd.Timestamp("2020-01-01")

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def train_symbol(symbol: str, panel: pd.DataFrame) -> None:
    sym = symbol.lower()
    df_sym = panel[panel["symbol"].str.lower() == sym].copy()
    if df_sym.empty:
        print(f"[{sym}] no data, skipping")
        return

    # train only on history before cutoff
    df_sym = df_sym[df_sym["date"] < TRAIN_END_DATE]
    if df_sym.empty or len(df_sym) < 200:
        print(f"[{sym}] no data before {TRAIN_END_DATE.date()}, skipping")
        return

    df_sym = add_stock_indicators(df_sym)
    all_seq_cols = [c for group in SEQ_GROUPS for c in group]
    all_req = all_seq_cols + TAB_FEATURES + REGIME_FEATURES + [TARGET]

    df_sym = df_sym.dropna(subset=all_req)
    df_sym = df_sym.sort_values("date")

    if len(df_sym) < 200:
        print(f"[{sym}] too few rows after feature prep, skipping")
        return

    n_total = len(df_sym)
    n_test = int(n_total * TEST_SIZE)
    remaining = n_total - n_test
    n_val = int(remaining * (VAL_SIZE / (1.0 - TEST_SIZE)))
    n_train = remaining - n_val

    train_df = df_sym.iloc[:n_train]
    val_df = df_sym.iloc[n_train : n_train + n_val]
    test_df = df_sym.iloc[n_train + n_val :]

    print(f"[{sym}] train={len(train_df)} val={len(val_df)} test={len(test_df)}")

    seq_train = build_seq_array(train_df)
    seq_val = build_seq_array(val_df)
    seq_test = build_seq_array(test_df)

    tab_train = train_df[TAB_FEATURES].to_numpy(dtype=np.float32)
    tab_val = val_df[TAB_FEATURES].to_numpy(dtype=np.float32)
    tab_test = test_df[TAB_FEATURES].to_numpy(dtype=np.float32)

    reg_train = train_df[REGIME_FEATURES].to_numpy(dtype=np.float32)
    reg_val = val_df[REGIME_FEATURES].to_numpy(dtype=np.float32)
    reg_test = test_df[REGIME_FEATURES].to_numpy(dtype=np.float32)

    y_train = train_df[TARGET].to_numpy(dtype=np.float32)
    y_val = val_df[TARGET].to_numpy(dtype=np.float32)
    y_test = test_df[TARGET].to_numpy(dtype=np.float32)

    seq_scaler = TimeSeriesScaler()
    tab_scaler = TimeSeriesScaler()
    reg_scaler = TimeSeriesScaler()

    seq_flat_train = seq_train.reshape(seq_train.shape[0], -1)
    seq_scaler.fit(seq_flat_train)
    seq_train_scaled = seq_scaler.transform(seq_flat_train).reshape(seq_train.shape)
    seq_val_scaled = seq_scaler.transform(seq_val.reshape(seq_val.shape[0], -1)).reshape(
        seq_val.shape
    )
    seq_test_scaled = seq_scaler.transform(seq_test.reshape(seq_test.shape[0], -1)).reshape(
        seq_test.shape
    )

    tab_scaler.fit(tab_train)
    tab_train_scaled = tab_scaler.transform(tab_train)
    tab_val_scaled = tab_scaler.transform(tab_val)
    tab_test_scaled = tab_scaler.transform(tab_test)

    reg_scaler.fit(reg_train)
    reg_train_scaled = reg_scaler.transform(reg_train)
    reg_val_scaled = reg_scaler.transform(reg_val)
    reg_test_scaled = reg_scaler.transform(reg_test)

    X_seq_train = torch.tensor(seq_train_scaled, dtype=torch.float32, device=DEVICE)
    X_tab_train = torch.tensor(tab_train_scaled, dtype=torch.float32, device=DEVICE)
    X_reg_train = torch.tensor(reg_train_scaled, dtype=torch.float32, device=DEVICE)
    y_train_t = torch.tensor(y_train, dtype=torch.float32, device=DEVICE).view(-1, 1)

    X_seq_val = torch.tensor(seq_val_scaled, dtype=torch.float32, device=DEVICE)
    X_tab_val = torch.tensor(tab_val_scaled, dtype=torch.float32, device=DEVICE)
    X_reg_val = torch.tensor(reg_val_scaled, dtype=torch.float32, device=DEVICE)
    y_val_t = torch.tensor(y_val, dtype=torch.float32, device=DEVICE).view(-1, 1)

    X_seq_test = torch.tensor(seq_test_scaled, dtype=torch.float32, device=DEVICE)
    X_tab_test = torch.tensor(tab_test_scaled, dtype=torch.float32, device=DEVICE)
    X_reg_test = torch.tensor(reg_test_scaled, dtype=torch.float32, device=DEVICE)
    y_test_t = torch.tensor(y_test, dtype=torch.float32, device=DEVICE).view(-1, 1)

    train_ds = TensorDataset(X_seq_train, X_tab_train, X_reg_train, y_train_t)
    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)

    core = HybridLSTM(
        seq_input_size=SEQ_INPUT_SIZE,
        tab_input_size=len(TAB_FEATURES),
        lstm_hidden=LSTM_HIDDEN,
        lstm_layers=LSTM_LAYERS,
        tab_hidden=TAB_HIDDEN,
        head_hidden=HEAD_HIDDEN,
        dropout=DROPOUT,
    )
    model = RegimeGatedModel(
        base_model=core,
        regime_input_size=len(REGIME_FEATURES),
        regime_hidden=REGIME_HIDDEN,
    ).to(DEVICE)

    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.SmoothL1Loss()

    best_val = float("inf")
    best_state = None
    patience = 0

    for epoch in range(NUM_EPOCHS):
        model.train()
        running = 0.0
        for seq_b, tab_b, reg_b, y_b in train_loader:
            optimizer.zero_grad()
            pred = model(seq_b, tab_b, reg_b)
            loss = criterion(pred, y_b)
            loss.backward()
            optimizer.step()
            running += loss.item() * len(seq_b)

        model.eval()
        with torch.no_grad():
            val_pred = model(X_seq_val, X_tab_val, X_reg_val)
            val_loss = criterion(val_pred, y_val_t).item()

        avg_train = running / len(train_ds)
        if (epoch + 1) % 50 == 0:
            print(f"[{sym}] epoch {epoch+1} train={avg_train:.6f} val={val_loss:.6f}")

        if val_loss < best_val:
            best_val = val_loss
            best_state = model.state_dict()
            patience = 0
        else:
            patience += 1

        if patience >= PATIENCE:
            print(f"[{sym}] early stop at epoch {epoch+1}")
            break

    if best_state is not None:
        model.load_state_dict(best_state)

    model.eval()
    with torch.no_grad():
        test_pred = model(X_seq_test, X_tab_test, X_reg_test)
        test_loss = criterion(test_pred, y_test_t).item()
    print(f"[{sym}] test MSE={test_loss:.6f}")

    ckpt = {
        "model_state_dict": model.state_dict(),
        "seq_input_size": SEQ_INPUT_SIZE,
        "tab_input_size": len(TAB_FEATURES),
        "regime_input_size": len(REGIME_FEATURES),
        "seq_len": LAGS,
        "lstm_hidden": LSTM_HIDDEN,
        "lstm_layers": LSTM_LAYERS,
        "tab_hidden": TAB_HIDDEN,
        "head_hidden": HEAD_HIDDEN,
        "regime_hidden": REGIME_HIDDEN,
        "dropout": DROPOUT,
    }
    model_path = MODELS_DIR / f"{sym}_hybrid_lstm.pth"
    torch.save(ckpt, model_path)

    seq_scaler.save(str(MODELS_DIR / f"{sym}_seq_scaler.json"))
    tab_scaler.save(str(MODELS_DIR / f"{sym}_tab_scaler.json"))
    reg_scaler.save(str(MODELS_DIR / f"{sym}_reg_scaler.json"))

    print(f"[{sym}] saved model and scalers")


def main() -> None:
    if not DATA_PATH.exists():
        raise SystemExit(f"Missing combined panel at {DATA_PATH}")

    panel = pd.read_parquet(DATA_PATH)
    panel = panel.loc[:, ~panel.columns.str.contains("^Unnamed")]
    panel["date"] = pd.to_datetime(panel["date"])
    panel["symbol"] = panel["symbol"].str.lower()

    panel = add_wig20_features(panel)
    panel = merge_strategy_signals(panel)

    for sym in SYMBOLS:
        train_symbol(sym, panel)


if __name__ == "__main__":
    main()
