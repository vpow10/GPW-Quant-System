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
features = [f"log_return_lag{lag}" for lag in range(1, 5)]
target = "ret_1d_log"

test_size = 0.25
num_epochs = 400
batch_size = 64
learning_rate = 0.0005

# parametry fee do backtestu
maker_fee = 0.0001
taker_fee = 0.0003
roundtrip_fee_log = np.log(1 - 2 * taker_fee)

# ========= DEFINICJA MODELU =========


class AdvancedModel(nn.Module):
    def __init__(self, input_features, hidden_sizes=[16, 32, 16], dropout_rate=0.3):
        super(AdvancedModel, self).__init__()
        layers = []
        in_features = input_features

        for hidden_size in hidden_sizes:
            layers.append(nn.Linear(in_features, hidden_size))
            layers.append(nn.LeakyReLU())
            layers.append(nn.Dropout(dropout_rate))
            in_features = hidden_size

        layers.append(nn.Linear(in_features, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, x):
        return self.network(x)


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
    for lag in range(1, 5):
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
        print(f"{symbol}: brak danych w time_series_dict – pomijam.")  # noqa
        continue

    df = time_series_dict[symbol].copy()

    # upewnij się, że masz wszystkie potrzebne kolumny
    if not all(col in df.columns for col in features + [target]):
        print(f"{symbol}: brakuje kolumn cech/targetu – pomijam.")  # noqa
        continue

    df = df.dropna(subset=features + [target])

    if len(df) < 50:  # proste zabezpieczenie
        print(f"{symbol}: za mało obserwacji ({len(df)}) – pomijam.")  # noqa
        continue

    # train / test split
    split_idx = int(len(df) * (1 - test_size))
    ts_train = df.iloc[:split_idx]
    ts_test = df.iloc[split_idx:]

    X_train = torch.tensor(ts_train[features].to_numpy(), dtype=torch.float32)
    X_test = torch.tensor(ts_test[features].to_numpy(), dtype=torch.float32)
    y_train = torch.tensor(ts_train[target].to_numpy(), dtype=torch.float32).reshape(-1, 1)
    y_test = torch.tensor(ts_test[target].to_numpy(), dtype=torch.float32).reshape(-1, 1)

    input_features = X_train.shape[1]
    model = AdvancedModel(input_features)

    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=learning_rate)

    print(f"\n=== Trening modelu dla symbolu: {symbol} (n={len(df)}) ===")  # noqa

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
            print(f"{symbol} | Epoch [{epoch + 1}/{num_epochs}], Loss: {epoch_loss:.6f}")  # noqa

    # ewaluacja
    model.eval()
    with torch.no_grad():
        y_hat = model(X_test).numpy()
        test_loss = criterion(torch.tensor(y_hat, dtype=torch.float32), y_test).item()

    # backtest w Polars
    trade_results = (
        pl.DataFrame(
            {
                "y_hat": y_hat.squeeze(),
                "y": y_test.numpy().squeeze(),
            }
        )
        .with_columns(
            (pl.col("y_hat").sign() == pl.col("y").sign()).alias("is_won"),
            pl.col("y_hat").sign().alias("signal"),
        )
        .with_columns((pl.col("signal") * pl.col("y")).alias("trade_log_return"))
        .with_columns(pl.lit(roundtrip_fee_log).alias("tx_fee_log"))
        .with_columns(
            (pl.col("trade_log_return") + pl.col("tx_fee_log")).alias("trade_log_return_net")
        )
        .with_columns(pl.col("trade_log_return_net").cum_sum().alias("equity_curve_net"))
    )

    win_rate = trade_results["is_won"].mean()
    final_equity = trade_results["equity_curve_net"][-1]

    print(  # noqa
        f"{symbol} | Test MSE: {test_loss:.6f}, "  # noqa
        f"Win rate: {win_rate:.4f}, Final equity (log): {final_equity:.4f}"  # noqa
    )  # noqa

    # zapis modelu do pliku
    model_path = os.path.join(MODELS_DIR, f"{symbol}_advanced_model.pth")
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "input_features": input_features,
            "features": features,
            "symbol": symbol,
        },
        model_path,
    )

    # zapis wyników backtestu do csv (bez to_pandas / pyarrow)
    backtest_path = os.path.join(MODELS_DIR, f"{symbol}_backtest.csv")
    trade_results.write_csv(backtest_path)

    # dodanie do podsumowania
    results_summary.append(
        {
            "symbol": symbol,
            "n_obs": len(df),
            "test_loss": test_loss,
            "win_rate": float(win_rate),
            "final_equity_log": float(final_equity),
            "model_path": model_path,
            "backtest_path": backtest_path,
        }
    )

# zapis zbiorczego podsumowania
if results_summary:
    summary_df = pd.DataFrame(results_summary)
    summary_path = os.path.join(MODELS_DIR, "models_summary.csv")
    summary_df.to_csv(summary_path, index=False)
    print(f"\nZapisano podsumowanie modeli do: {summary_path}")  # noqa
else:
    print("\nBrak wytrenowanych modeli (results_summary jest puste).")  # noqa
