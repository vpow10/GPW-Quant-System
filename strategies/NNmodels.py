from typing import Any, Dict

import torch
import torch.nn as nn


class HybridLSTM(nn.Module):
    """
    LSTM over price history + MLP over tabular factors (strategies, WIG20, etc.).
    Output: 1-step-ahead return prediction (regression).
    """

    def __init__(
        self,
        seq_input_size: int,
        tab_input_size: int,
        lstm_hidden: int = 64,
        lstm_layers: int = 1,
        tab_hidden: int = 32,
        head_hidden: int = 64,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=seq_input_size,
            hidden_size=lstm_hidden,
            num_layers=lstm_layers,
            batch_first=True,
            dropout=dropout if lstm_layers > 1 else 0.0,
        )

        self.tab_mlp = nn.Sequential(
            nn.Linear(tab_input_size, tab_hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(tab_hidden, tab_hidden),
            nn.ReLU(),
        )

        self.head = nn.Sequential(
            nn.Linear(lstm_hidden + tab_hidden, head_hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(head_hidden, 1),
        )

    def forward(self, seq_x: torch.Tensor, tab_x: torch.Tensor) -> torch.Tensor:
        # seq_x: (batch, seq_len, seq_input_size)
        # tab_x: (batch, tab_input_size)
        seq_out, _ = self.lstm(seq_x)
        seq_last = seq_out[:, -1, :]
        tab_feat = self.tab_mlp(tab_x)
        x = torch.cat([seq_last, tab_feat], dim=1)
        out = self.head(x)
        return out


class RegimeGatedModel(nn.Module):
    """
    Wraps any base model and multiplies its output by a regime gate in [0, 1].
    regime_x should contain WIG20 features or similar market-state features.
    """

    def __init__(
        self,
        base_model: nn.Module,
        regime_input_size: int,
        regime_hidden: int = 16,
    ) -> None:
        super().__init__()
        self.base_model = base_model
        self.regime_net = nn.Sequential(
            nn.Linear(regime_input_size, regime_hidden),
            nn.ReLU(),
            nn.Linear(regime_hidden, 1),
            nn.Sigmoid(),
        )

    def forward(
        self,
        seq_x: torch.Tensor,
        tab_x: torch.Tensor,
        regime_x: torch.Tensor,
    ) -> torch.Tensor:
        base_pred = self.base_model(seq_x, tab_x)  # (batch, 1)
        gate = self.regime_net(regime_x)  # (batch, 1), in [0, 1]
        return base_pred * gate


def build_hybrid_batch(
    seq_array,
    tab_array,
    regime_array=None,
    target_array=None,
    device: str = "cpu",
) -> Dict[str, Any]:
    """
    Helper for building batch dict.
    seq_array: np.ndarray (N, seq_len, seq_input_size)
    tab_array: np.ndarray (N, tab_input_size)
    regime_array: np.ndarray (N, regime_input_size) or None
    target_array: np.ndarray (N,) or (N,1) or None
    """
    batch: Dict[str, Any] = {}
    batch["seq_x"] = torch.tensor(seq_array, dtype=torch.float32, device=device)
    batch["tab_x"] = torch.tensor(tab_array, dtype=torch.float32, device=device)

    if regime_array is not None:
        batch["regime_x"] = torch.tensor(regime_array, dtype=torch.float32, device=device)

    if target_array is not None:
        y = torch.tensor(target_array, dtype=torch.float32, device=device)
        if y.ndim == 1:
            y = y.view(-1, 1)
        batch["y"] = y

    return batch
