import json
from typing import Any, Generator, Tuple

import numpy as np
import polars as pl
import torch
import torch.nn as nn


# ========= MODEL =========
class LSTMModel(nn.Module):
    def __init__(
        self,
        input_size: int,
        hidden_size: int = 64,
        num_layers: int = 1,
        dropout: float = 0.0,
    ):
        """
        Standard LSTM model for regression.
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

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, input_size)
        out, _ = self.lstm(x)
        # Use the last hidden state from the last sequence step
        last_hidden = out[:, -1, :]
        out = self.fc(last_hidden)
        return out


# ========= SCALER =========
class TimeSeriesScaler:
    """
    Standard scaler (Z-score) implementation using NumPy.
    Saves/loads mean and var to JSON for reproducibility.
    """

    def __init__(self):
        self.mean: np.ndarray | None = None
        self.scale: np.ndarray | None = None

    def fit(self, X: np.ndarray) -> None:
        """Compute mean and std to be used for later scaling."""
        self.mean = np.mean(X, axis=0)
        self.scale = np.std(X, axis=0)
        # Avoid division by zero
        self.scale[self.scale == 0] = 1.0

    def transform(self, X: np.ndarray) -> np.ndarray:
        """Perform standardization by centering and scaling."""
        if self.mean is None or self.scale is None:
            raise ValueError("Scaler has not been fitted yet.")
        # Cast to avoid "Returning Any" error
        return np.array((X - self.mean) / self.scale)

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        self.fit(X)
        return self.transform(X)

    def save(self, path: str) -> None:
        """Save scaler parameters to JSON."""
        data = {
            "mean": self.mean.tolist() if self.mean is not None else [],
            "scale": self.scale.tolist() if self.scale is not None else [],
        }
        with open(path, "w") as f:
            json.dump(data, f)

    def load(self, path: str) -> None:
        """Load scaler parameters from JSON."""
        with open(path, "r") as f:
            data = json.load(f)
        self.mean = np.array(data["mean"])
        self.scale = np.array(data["scale"])


# ========= DATA HELPERS =========


def prepare_lstm_data(
    df: pl.DataFrame | Any,
    features: list[str],
    target: str = "",
    seq_len: int = 1,
    input_size: int = 1,
):
    """
    Reshapes the flat feature columns into LSTM format.
    Assumes features are already lagged columns.

    Returns:
        X: tensor (N, seq_len, input_size)
        y: tensor (N, 1) or None
    """
    # This logic assumes the 'features' list is ordered by time (lag1, lag2...)
    # OR that we want to treat each feature as a separate channel?
    # Original code: X_train_flat.view(-1, SEQ_LEN, INPUT_SIZE)
    # This implies features was [lag1, lag2, lag3, lag4] -> seq_len=4, input=1

    # We will stick to that logic for now, but explicit is better.

    # Convert to numpy
    if hasattr(df, "to_numpy"):
        X_numpy = df[features].to_numpy()
        if target:
            y_numpy = df[target].to_numpy()
        else:
            y_numpy = None
    elif isinstance(df, pl.DataFrame):
        X_numpy = df.select(features).to_numpy()
        if target:
            y_numpy = df.select(target).to_numpy()
        else:
            y_numpy = None
    else:
        # Pandas fallback
        X_numpy = df[features].to_numpy()
        if target:
            y_numpy = df[target].to_numpy()
        else:
            y_numpy = None

    # Reshape
    # X_numpy is (N, total_features)
    # We want (N, seq_len, input_size) where seq_len * input_size = total_features

    # Validate
    if X_numpy.shape[1] != seq_len * input_size:
        raise ValueError(
            f"Feature count {X_numpy.shape[1]} does not match reshaped size "
            f"seq_len={seq_len} * input_size={input_size} = {seq_len*input_size}"
        )

    X_tensor = torch.tensor(X_numpy, dtype=torch.float32).view(-1, seq_len, input_size)

    y_tensor = None
    if y_numpy is not None:
        y_tensor = torch.tensor(y_numpy, dtype=torch.float32).reshape(-1, 1)

    return X_tensor, y_tensor


def create_batches(
    X: torch.Tensor, y: torch.Tensor, batch_size: int
) -> Generator[Tuple[torch.Tensor, torch.Tensor], None, None]:
    """Yields batches of X and y."""
    n_samples = len(X)
    indices = torch.randperm(n_samples)  # Shuffle for training

    for i in range(0, n_samples, batch_size):
        batch_indices = indices[i : i + batch_size]
        yield X[batch_indices], y[batch_indices]
