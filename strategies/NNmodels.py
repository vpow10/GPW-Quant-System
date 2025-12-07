import os

import numpy as np
import pandas as pd
import polars as pl
import torch
import torch.nn as nn
import torch.optim as optim

# ========= KONFIGURACJA =========

DATA_PATH = "data/processed/reports/combined.csv"
MODELS_DIR = "./models"

os.makedirs(MODELS_DIR, exist_ok=True)

# lista symboli, które chcesz modelować
symbols = [
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

# cechy i target
features = [f"log_return_lag{lag}" for lag in range(1, 25)]
target = "ret_1d_log"

test_size = 0.25
num_epochs = 6000
batch_size = 64
learning_rate = 0.005

# parametry fee do backtestu
maker_fee = 0.0001
taker_fee = 0.003
roundtrip_fee_log = np.log(1 - 2 * taker_fee)

# parametry sekwencji do LSTM
SEQ_LEN = len(features)   # 4 lags -> długość sekwencji
INPUT_SIZE = 1            # 1 cecha na krok czasowy

# ========= DEFINICJA MODELU (LSTM) =========


class LSTMModel(nn.Module):
    def __init__(
        self,
        input_size: int = INPUT_SIZE,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.0,
    ):
        """
        Prosty model LSTM:
        - wejście: (batch, seq_len, input_size)
        - wyjście: jedna liczba (prognoza ret_1d_log)
        """
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.fc = nn.Linear(hidden_size, 1)

    def forward(self, x):
        # x: (batch, seq_len, input_size)
        out, (hn, cn) = self.lstm(x)
        # używamy ostatniego stanu ukrytego ostatniej warstwy
        last_hidden = hn[-1]  # (batch, hidden_size)
        out = self.fc(last_hidden)  # (batch, 1)
        return out


# ========= WCZYTANIE DANYCH I PRZETWARZANIE =========

ts = pd.read_csv(DATA_PATH)

# usunięcie kolumn typu "Unnamed: 0"
ts = ts.loc[:, ~ts.columns.str.contains("^Unnamed")]

required_columns = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "ret_1d",
    "flag_abnormal_gap",
    "symbol",
]

# zostaw tylko wymagane kolumny, które faktycznie istnieją
cols_present = [c for c in required_columns if c in ts.columns]
ts = ts[cols_present]

# słownik szeregów czasowych per symbol
time_series_dict = {}

for symbol, group in ts.groupby("symbol"):
    group = group.sort_values(by="date")

    # logarytmiczny zwrot
    group["ret_1d_log"] = np.log(1 + group["ret_1d"])

    # lags dla ret_1d i ret_1d_log
    for lag in range(1, 25):
        group[f"ireturn_lag{lag}"] = group["ret_1d"].shift(lag)
        group[f"log_return_lag{lag}"] = group["ret_1d_log"].shift(lag)

    group = group.dropna()
    time_series_dict[symbol] = group


# ========= FUNKCJA TWORZENIA BATCHY =========


def create_batches(X, y, batch_size):
    for i in range(0, len(X), batch_size):
        yield X[i : i + batch_size], y[i : i + batch_size]


# ========= TRENING I ZAPIS MODELI =========

results_summary = []

for symbol in symbols:
    if symbol not in time_series_dict:
        print(f"{symbol}: brak danych w time_series_dict – pomijam.")
        continue

    df = time_series_dict[symbol].copy()

    # upewnij się, że masz wszystkie potrzebne kolumny
    if not all(col in df.columns for col in features + [target]):
        print(f"{symbol}: brakuje kolumn cech/targetu – pomijam.")
        continue

    df = df.dropna(subset=features + [target])

    if len(df) < 50:  # proste zabezpieczenie
        print(f"{symbol}: za mało obserwacji ({len(df)}) – pomijam.")
        continue

    # train / test split
    split_idx = int(len(df) * (1 - test_size))
    ts_train = df.iloc[:split_idx]
    ts_test = df.iloc[split_idx:]

    # --- PRZYGOTOWANIE DANYCH DLA LSTM ---
    # z [N, len(features)] -> [N, SEQ_LEN, INPUT_SIZE]
    X_train_flat = torch.tensor(
        ts_train[features].to_numpy(), dtype=torch.float32
    )
    X_test_flat = torch.tensor(
        ts_test[features].to_numpy(), dtype=torch.float32
    )

    X_train = X_train_flat.view(-1, SEQ_LEN, INPUT_SIZE)
    X_test = X_test_flat.view(-1, SEQ_LEN, INPUT_SIZE)

    y_train = torch.tensor(
        ts_train[target].to_numpy(), dtype=torch.float32
    ).reshape(-1, 1)
    y_test = torch.tensor(
        ts_test[target].to_numpy(), dtype=torch.float32
    ).reshape(-1, 1)

    model = LSTMModel(input_size=INPUT_SIZE, hidden_size=32, num_layers=1, dropout=0.0)

    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)

    print(f"\n=== Trening modelu LSTM dla symbolu: {symbol} (n={len(df)}) ===")

    # trening
    for epoch in range(num_epochs):
        model.train()
        epoch_loss = 0.0

        for X_batch, y_batch in create_batches(X_train, y_train, batch_size):
            optimizer.zero_grad()
            outputs = model(X_batch)
            loss = criterion(outputs, y_batch)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

        if (epoch + 1) % 50 == 0:
            print(f"{symbol} | Epoch [{epoch + 1}/{num_epochs}], Loss: {epoch_loss:.6f}")

    # ewaluacja
    model.eval()
    with torch.no_grad():
        y_hat = model(X_test).numpy()
        test_loss = criterion(torch.tensor(y_hat, dtype=torch.float32), y_test).item()

    # backtest w Polars (prosta wersja jak wcześniej)
    threshold = 0.0  # na razie bez progu, o tym za chwilę

    trade_results = (
        pl.DataFrame(
            {
                "y_hat": y_hat.squeeze(),
                "y": y_test.numpy().squeeze(),
            }
        )
        # surowy sygnał z modelu
        .with_columns(
            pl.col("y_hat").sign().alias("raw_signal")
        )
        # opcjonalnie próg zaufania (patrz pkt 2)
        .with_columns(
            pl.when(pl.col("y_hat").abs() <= threshold)
            .then(0)                     # sygnał zbyt słaby -> brak pozycji
            .otherwise(pl.col("raw_signal"))
            .alias("signal")
        )
        # poprzednia pozycja
        .with_columns(
            pl.col("signal").shift(1).fill_null(0).alias("prev_signal")
        )
        # czy nastąpiła transakcja (zmiana pozycji)?
        .with_columns(
            (pl.col("signal") != pl.col("prev_signal"))
            .cast(pl.Int8)
            .alias("is_trade")
        )
        # zwrot z pozycji (brutto)
        .with_columns(
            (pl.col("signal") * pl.col("y")).alias("trade_log_return")
        )
        # opłata tylko, gdy jest trade
        .with_columns(
            (pl.col("is_trade") * roundtrip_fee_log).alias("tx_fee_log")
        )
        # netto
        .with_columns(
            (pl.col("trade_log_return") + pl.col("tx_fee_log")).alias(
                "trade_log_return_net"
            )
        )
        .with_columns(
            pl.col("trade_log_return_net").cum_sum().alias("equity_curve_net")
        )
    )


    final_equity = trade_results["equity_curve_net"][-1]

    print(
        f"{symbol} | Test MSE: {test_loss:.6f}, "
        f"Final equity (log): {final_equity:.4f}"
    )

    # zapis modelu do pliku
    model_path = os.path.join(MODELS_DIR, f"{symbol}_lstm_model.pth")
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "features": features,
            "symbol": symbol,
            "seq_len": SEQ_LEN,
            "input_size": INPUT_SIZE,
        },
        model_path,
    )

    # zapis wyników backtestu do csv
    backtest_path = os.path.join(MODELS_DIR, f"{symbol}_backtest_lstm.csv")
    trade_results.write_csv(backtest_path)

    # dodanie do podsumowania
    results_summary.append(
        {
            "symbol": symbol,
            "n_obs": len(df),
            "test_loss": test_loss,
            "final_equity_log": float(final_equity),
            "model_path": model_path,
            "backtest_path": backtest_path,
        }
    )

# zapis zbiorczego podsumowania
if results_summary:
    summary_df = pd.DataFrame(results_summary)
    summary_path = os.path.join(MODELS_DIR, "models_summary_lstm.csv")
    summary_df.to_csv(summary_path, index=False)
    print(f"\nZapisano podsumowanie modeli do: {summary_path}")
else:
    print("\nBrak wytrenowanych modeli (results_summary jest puste).")
