# Moduł Testów (Tests)

Ten katalog zawiera testy jednostkowe i integracyjne dla całego systemu. Używamy biblioteki `pytest` do uruchamiania testów.

## Kluczowe Pliki

- **`test_strategies.py`**: Testy sprawdzające poprawność implementacji strategii (czy generują sygnały, czy nie wyrzucają błędów).
- **`test_rsi.py`**: Szczegółowe testy logiki strategii RSI (poprawność obliczeń, sygnały generowane na wzorcowych danych).
- **`test_run_backtest.py`**: Testy silnika backtestu (sprawdzenie przepływu danych wejściowych i generowania raportów).
- **`test_momentum.py`** / **`test_mean_reversion.py`**: Testy jednostkowe dla pozostałych strategii.
- **`test_engine.py`**: Testy dla głównego silnika backtestów
## Instrukcja Uruchomienia

Aby uruchomić wszystkie testy, wykonaj poniższe polecenie z głównego katalogu projektu:

```bash
python -m pytest
```

### Uruchamianie konkretnego pliku testowego

Jeśli chcesz uruchomić tylko testy związane np. ze strategiami:

```bash
python -m pytest tests/test_strategies.py
```

### Pomijanie testów ML

Testy strategii opartych na uczeniu maszynowym (LSTM) są domyślnie pomijane, jeśli w środowisku nie ma zainstalowanej biblioteki `torch`.
