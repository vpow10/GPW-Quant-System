# noqa: T201
import copy
import os

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim

from strategies.lstm_utils import LSTMModel, TimeSeriesScaler, create_batches

# ========= CONFIG =========
DATA_PATH = "data/processed/reports/combined.csv"
MODELS_DIR = "./models"
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

# Hyperparameters
TEST_SIZE = 0.20
VAL_SIZE = 0.15  # of the remaining 80%? Or total?
# Let's do: Test=20%, Val=15%, Train=65%
NUM_EPOCHS = 1000  # Reduced from 6000
PATIENCE = 50  # Early stopping patience
BATCH_SIZE = 64
LEARNING_RATE = 0.001
HIDDEN_SIZE = 32
NUM_LAYERS = 1
DROPOUT = 0.0

# Feature Config
LAGS = 24


def get_features_list():
    """Returns list of feature column names."""
    feat = [f"log_return_lag{lag}" for lag in range(1, LAGS + 1)]
    # Add volume features
    feat += [f"log_vol_chg_lag{lag}" for lag in range(1, LAGS + 1)]
    return feat


FEATURES = get_features_list()
TARGET = "ret_1d_log"

SEQ_LEN = LAGS
INPUT_SIZE = 2  # (return, volume) per time step


def load_and_process_data(path: str):
    print(f"Loading data from {path}...")
    ts = pd.read_csv(path)
    ts = ts.loc[:, ~ts.columns.str.contains("^Unnamed")]

    required_cols = ["date", "symbol", "ret_1d", "volume"]
    # minimal check
    for c in required_cols:
        if c not in ts.columns:
            raise ValueError(f"Missing column: {c}")

    return ts


def preprocess_symbol_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").copy()

    # Target
    df["ret_1d_log"] = np.log1p(df["ret_1d"])

    # Feature Engineering
    # Volume Change
    # avoid log(0)
    df["volume"] = df["volume"].replace(0, 1)
    df["vol_log"] = np.log(df["volume"])
    df["vol_log_chg"] = df["vol_log"].diff()

    # Lags
    for lag in range(1, LAGS + 1):
        df[f"log_return_lag{lag}"] = df["ret_1d_log"].shift(lag)
        df[f"log_vol_chg_lag{lag}"] = df["vol_log_chg"].shift(lag)

    df = df.dropna()
    return df


def train_model_for_symbol(symbol: str, df_symbol: pd.DataFrame):
    print(f"\nProcessing {symbol} (n={len(df_symbol)})...")

    # 1. Split
    n_total = len(df_symbol)
    n_test = int(n_total * TEST_SIZE)
    remaining = n_total - n_test
    n_val = int(remaining * (VAL_SIZE / (1 - TEST_SIZE)))
    n_train = remaining - n_val

    train_df = df_symbol.iloc[:n_train]
    val_df = df_symbol.iloc[n_train : n_train + n_val]
    test_df = df_symbol.iloc[n_train + n_val :]

    print(f"Split: Train={len(train_df)}, Val={len(val_df)}, Test={len(test_df)}")

    if len(train_df) < 50 or len(val_df) < 10:
        print("Not enough data to train. Skipping.")
        return

    # 2. Fit Scaler (Train only)
    scaler = TimeSeriesScaler()
    X_train_raw = train_df[FEATURES].to_numpy()  # (N, features)
    scaler.fit(X_train_raw)

    # 3. Transform & Prepare Tensors
    # Helper to transform and convert
    def get_tensors(dframe):
        X_np = scaler.transform(dframe[FEATURES].to_numpy())
        y_np = dframe[TARGET].to_numpy()

        # We need to reshape carefully
        # FEATURES order is: [ret_lag1, ret_lag2..., vol_lag1, vol_lag2...]
        # But we want (seq_len, input_size) where input_size=2 (ret, vol)
        # So we need to reorder or reshape.

        # Current flat structure:
        # [ret_l1, ret_l2... ret_l24, vol_l1... vol_l24]
        # We want:
        # t=1: [ret_l1, vol_l1]
        # t=2: [ret_l2, vol_l2]
        # ...

        # Let's reshape manually using numpy
        N = X_np.shape[0]
        X_reshaped = np.zeros((N, SEQ_LEN, INPUT_SIZE))

        # ret lags
        X_reshaped[:, :, 0] = X_np[:, :SEQ_LEN]
        # vol lags
        X_reshaped[:, :, 1] = X_np[:, SEQ_LEN:]

        X_t = torch.tensor(X_reshaped, dtype=torch.float32)
        y_t = torch.tensor(y_np, dtype=torch.float32).reshape(-1, 1)
        return X_t, y_t

    X_train, y_train = get_tensors(train_df)
    X_val, y_val = get_tensors(val_df)
    X_test, y_test = get_tensors(test_df)

    # 4. Model Setup
    model = LSTMModel(
        input_size=INPUT_SIZE, hidden_size=HIDDEN_SIZE, num_layers=NUM_LAYERS, dropout=DROPOUT
    )
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)

    # 5. Training Loop
    best_val_loss = float("inf")
    best_model_state = None
    patience_counter = 0

    for epoch in range(NUM_EPOCHS):
        model.train()
        epoch_loss = 0.0
        # Shuffle batches
        for X_b, y_b in create_batches(X_train, y_train, BATCH_SIZE):
            optimizer.zero_grad()
            out = model(X_b)
            loss = criterion(out, y_b)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

        # Validation
        model.eval()
        with torch.no_grad():
            val_out = model(X_val)
            val_loss = criterion(val_out, y_val).item()

        if (epoch + 1) % 50 == 0:
            print(
                f"Epoch [{epoch+1}/{NUM_EPOCHS}] Train Loss: {epoch_loss/len(X_train):.6f} | Val Loss: {val_loss:.6f}"
            )

        # Early Stopping Check
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_model_state = copy.deepcopy(model.state_dict())
            patience_counter = 0
        else:
            patience_counter += 1

        if patience_counter >= PATIENCE:
            print(f"Early stopping triggered at epoch {epoch+1}")
            break

    # 6. Evaluation on Test
    if best_model_state:
        model.load_state_dict(best_model_state)

    model.eval()
    with torch.no_grad():
        test_out = model(X_test)
        test_loss = criterion(test_out, y_test).item()

    print(f"Test MSE: {test_loss:.6f}")

    # 7. Save Artifacts
    save_dict = {
        "model_state_dict": model.state_dict(),
        "input_size": INPUT_SIZE,
        "seq_len": SEQ_LEN,
        "features": FEATURES,
        "hidden_size": HIDDEN_SIZE,
        "num_layers": NUM_LAYERS,
    }
    model_path = os.path.join(MODELS_DIR, f"{symbol}_lstm.pth")
    torch.save(save_dict, model_path)

    scaler_path = os.path.join(MODELS_DIR, f"{symbol}_scaler.json")
    scaler.save(scaler_path)

    print(f"Saved model to {model_path}")
    print(f"Saved scaler to {scaler_path}")


def main():
    full_df = load_and_process_data(DATA_PATH)

    for symbol in SYMBOLS:
        df_sym = full_df[full_df["symbol"] == symbol]
        if df_sym.empty:
            print(f"No data for {symbol}")
            continue

        # Preprocess (add lags)
        df_proc = preprocess_symbol_data(df_sym)

        train_model_for_symbol(symbol, df_proc)


if __name__ == "__main__":
    main()
