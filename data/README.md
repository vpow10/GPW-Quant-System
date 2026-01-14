# Moduł Danych (Data)

Ten katalog służy do przechowywania wszystkich danych używanych przez system (rynkowych, przetworzonych, sygnałów) oraz skryptów pomocniczych do zarządzania nimi.

## Struktura Katalogów

- **`raw/`**: Surowe dane rynkowe (format CSV lub JSON) pobrane bezpośrednio z zewnętrznych źródeł (np. Stooq, Saxo). Te pliki zazwyczaj nie są edytowane ręcznie.
- **`processed/`**: Dane oczyszczone i przetworzone, gotowe do użycia przez strategie i backtester (zazwyczaj format Parquet dla wydajności).
    - `processed/gpw/`: Przetworzone notowania dla spółek GPW i indeksów.
    - `processed/reports/`: Zagregowane dane (np. `combined.parquet`) używane przez skrypty sygnałowe.
- **`signals/`**: Wygenerowane sygnały transakcyjne przez strategie (każda strategia generuje własny plik, np. `rsi_14d_basic.parquet`).
- **`backtests/`**: Wyniki symulacji historycznych (pliki CSV z krzywą kapitału i metrykami).
- **`scripts/`**: Kolekcja skryptów Python do pobierania, aktualizacji i przetwarzania danych.

## Kluczowe Skrypty (`data/scripts/`)

- **`setup_pipeline.py`**: Skrypt "wszystko w jednym". Uruchamia pełny proces: pobranie danych historycznych, przetworzenie ich i wygenerowanie sygnałów dla wszystkich strategii. Idealny na początek pracy.
- **`stooq_fetch.py`**: Pobiera historyczne dane OHLCV (Open, High, Low, Close, Volume) z serwisu Stooq.pl dla zdefiniowanych tickerów.
- **`saxo_auth.py`**: Obsługuje proces autoryzacji OAuth z Saxo Bankiem (generowanie i odświeżanie tokenów).
- **`preprocess_gpw.py`**: Przetwarza surowe pliki CSV ze Stooq do wydajnego formatu Parquet, oblicza stopy zwrotu i łączy dane w jeden spójny zbiór.
- **`update_gpw_data.py`**: Służy do inkrementalnej aktualizacji danych (np. pobranie tylko dzisiejszej sesji) bez konieczności pobierania całej historii od nowa.

## Instrukcja Użycia

### 1. Pełna Inicjalizacja Danych

Jeśli uruchamiasz system po raz pierwszy, użyj tego polecenia, aby pobrać historię i przygotować wszystko:

```bash
python -m data.scripts.setup_pipeline
```

### 2. Pobieranie Danych Historycznych (Ręcznie)

Aby pobrać dane dla wszystkich spółek zdefiniowanych w `gpw_selected.csv`:

```bash
python -m data.scripts.stooq_fetch fetch-all
```

### 3. Autoryzacja Saxo Bank

Przed uruchomieniem handlu rzeczywistego (Live/Paper), musisz się zalogować:

```bash
python -m data.scripts.saxo_auth login
```
