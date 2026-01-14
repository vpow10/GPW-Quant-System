# Moduł Strategii (Strategies)

Ten folder zawiera implementacje logiki tradingowej, skrypty generujące sygnały oraz modele uczenia maszynowego. Wszystkie strategie dziedziczą po klasie bazowej `base.StrategyBase`.

## Kluczowe Pliki

### Logika i Konfiguracja
- **`config_strategies.py`**: Rejestr wszystkich dostępnych strategii wraz z ich konfiguracją parametrów. To tutaj definiujemy, jakie strategie są dostępne w systemie.
- **`run_strategies.py`**: Główny skrypt służący do przeliczania strategii na danych historycznych i generowania plików z sygnałami (format Parquet/CSV).
- **`base.py`**: Klasa bazowa `StrategyBase`, definiująca interfejs dla każdej strategii.
- **`indicators.py`**: Biblioteka funkcji obliczających wskaźniki analizy technicznej.

### Implementacje Strategii
- **`rsi.py`**: Strategia Mean Reversion oparta na wskaźniku RSI (Relative Strength Index).
- **`momentum.py`**: Strategia podążania za trendem (Time Series Momentum).
- **`mean_reversion.py`**: Strategia oparta na powrocie ceny do średniej (Z-Score).
- **`lstm_strategy.py`**: Strategia wykorzystująca prostą sieć neuronową LSTM do predykcji cen.
- **`hybrid_lstm_strategy.py`**: Zaawansowana strategia łącząca LSTM z podejściem klasyfikacyjnym i dodatkowymi cechami (wskaźniki techniczne).

### Uczenie Maszynowe
- **`train_lstm.py`** / **`train_hybrid_lstm.py`**: Skrypty do trenowania modeli sieci neuronowych.
- **`NNmodels.py`**: Definicje architektur sieci neuronowych (PyTorch).
- **`hybrid_features.py`**: Inżynieria cech (Feature Engineering) dla modelu hybrydowego.

## Instrukcja Użycia

### 1. Generowanie Sygnałów

Aby wygenerować sygnały dla wybranej strategii (np. `rsi_14d_basic`) na podstawie pobranych danych rynkowych:

```bash
# Z katalogu głównego projektu
python -m strategies.run_strategies \
    --strategies rsi_14d_basic \
    --input data/processed/reports/combined.parquet \
    --output-dir data/signals
```

### 2. Dodawanie Nowej Strategii

1. Utwórz nowy plik (np. `my_strategy.py`) i stwórz klasę dziedziczącą po `StrategyBase`.
2. Zaimplementuj metodę `generate_signals(df)`, która przyjmuje DataFrame z danymi i zwraca go z dodaną kolumną `signal` (wartości: 1 dla kupna, -1 dla sprzedaży, 0 neutralne).
3. Zarejestruj nową strategię i jej domyślne parametry w pliku `config_strategies.py`.

**Alternatywnie:** Możesz zdefiniować nową strategię w `config_strategies.py`, wykorzystując istniejącą klasę (np. `RsiStrategy`), ale zmieniając jej parametry (np. `window=20` zamiast `14`). Nie wymaga to tworzenia nowego pliku Python.

### 3. Trenowanie Modeli LSTM

Jeśli chcesz przetrenować model LSTM na nowych danych:

```bash
python -m strategies.train_hybrid_lstm
```

Skrypt ten wczyta dane, wytrenuje model i zapisze wagi w katalogu `strategies/models/` (lub odpowiednim podkatalogu).
