# Moduł Backtestu (Backtest Engine)

Katalog ten zawiera framework do przeprowadzania symulacji historycznych (backtestów), który pozwala zweryfikować skuteczność strategii inwestycyjnych na danych historycznych przed ich użyciem na realnym rynku.

## Kluczowe Pliki

- **`engine.py`**: Serce silnika backtestingowego. Klasa `BacktestEngine` odpowiada za:
    - Symulację portfela inwestycyjnego dzień po dniu.
    - Obliczanie zysków i strat (PnL).
    - Uwzględnianie kosztów transakcyjnych (prowizje) oraz poślizgów cenowych (slippage).
    - Kontrolę dźwigni finansowej (leverage checks).
- **`run_backtest.py`**: Interfejs wiersza poleceń (CLI) służący do uruchamiania backtestów na podstawie wcześniej wygenerowanych plików z sygnałami (format Parquet).

## Instrukcja Użycia

### Uruchomienie Backtestu Portfelowego

Aby przeprowadzić symulację, potrzebujesz pliku z sygnałami (np. wygenerowanego przez `strategies.run_strategies`).

Przykładowe polecenie uruchomienia backtestu dla strategii RSI:

```bash
python -m backtest.run_backtest \
    --signals data/signals/rsi_14d_basic.parquet \
    --mode portfolio \
    --initial-capital 100000 \
    --commission-bps 5 \
    --slippage-bps 5 \
    --benchmark data/processed/gpw/wig20.parquet
```

### Parametry:

- `--signals`: Ścieżka do pliku `.parquet` z sygnałami strategii.
- `--mode`: Tryb symulacji (zazwyczaj `portfolio`).
- `--initial-capital`: Kapitał początkowy (np. 100 000 PLN).
- `--commission-bps`: Prowizja w punktach bazowych (np. 5 bps = 0.05%).
- `--slippage-bps`: Symulowany poślizg cenowy w punktach bazowych.
- `--benchmark`: (Opcjonalnie) Ścieżka do danych benchmarku (np. indeksu WIG20) w celu porównania wyników.

### Wyniki

Skrypt wygeneruje raport w katalogu `data/backtests/`. Plik wynikowy (np. `rsi_14d_basic.daily.csv`) zawiera:
- Krzywą kapitału (Equity Curve).
- Statystyki dzienne portfela.
- Podsumowanie wyników (CAGR, Sharpe Ratio, Max Drawdown).

Wyniki te mogą być następnie wizualizowane w Dashboardzie (`app.web`).
