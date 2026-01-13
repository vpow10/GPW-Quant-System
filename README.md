# GPW Quant System

System algorytmicznego tradingu dla Giełdy Papierów Wartościowych w Warszawie (GPW), zawierający moduły do pobierania danych, analizy ilościowej, backtestingu strategii i automatycznego handlu.

## Uruchomienie

### 1. Konfiguracja środowiska
Upewnij się, że masz zainstalowane wymagane zależności:
```bash
pip install -r requirements.txt
```

### 2. Autoryzacja Saxo Bank
Aby korzystać z handlu rzeczywistego lub pobierać dane live z Saxo Bank:
1. Uzupełnij `.env` swoimi kluczami API (Client ID, Secret).
2. Uruchom skrypt autoryzacyjny, aby wygenerować pierwszy token:
   ```bash
   python -m data.scripts.saxo_auth login
   ```
   Postępuj zgodnie z instrukcjami w terminalu (logowanie w przeglądarce).

### 3. Aplikacja Webowa (Dashboard)
System posiada interfejs webowy do analizy wyników backtestów i monitorowania systemu.

Uruchom serwer developerski:
```bash
python -m app.web
```
Dashboard będzie dostępny pod adresem: `http://localhost:5000`

## Struktura Projektu

> **Wskazówka:** Większość poniższych katalogów zawiera własny plik `README.md` ze szczegółową dokumentacją techniczną.

- **`app/`**: Kod źródłowy aplikacji webowej (Flask) oraz logiki tradingowej (`daily_trader.py`).
- **`automation/`**: Skrypty i konfiguracje do automatyzacji zadań (cron), logi i raporty dzienne.
- **`backtest/`**: Silnik backtestingu (`engine.py`) oraz skrypty do uruchamiania symulacji historycznych.
- **`data/`**: Przechowywanie danych rynkowych (`processed/`), sygnałów (`signals/`) i wyników analiz.
    - `scripts/`: Skrypty pomocnicze do pobierania i przetwarzania danych (NBP, GPW, Saxo).
- **`strategies/`**: Implementacje strategii inwestycyjnych (RSI, Momentum, Mean Reversion) i ich konfiguracja.
- **`tests/`**: Testy jednostkowe (pytest).
- **`docs/`**: Dokumentacja techniczna i opisy strategii.

## Strategie

System obsługuje zarówno klasyczne strategie techniczne, jak i autorskie modele oparte na uczeniu maszynowym:


- **LSTM (Autorska)**: Model sieci neuronowej typu Long Short-Term Memory przewidujący przyszłe ceny.
- **Hybrid LSTM (Autorska)**: Zaawansowany model hybrydowy łączący LSTM z analizą wskaźników technicznych i rynkowych.
- **Momentum**: Strategia podążania za trendem (Trend Following).
- **Mean Reversion**: Strategia statystycznego powrotu do średniej (Z-score).
- **RSI Strategy**: Prosta strategia oparta na wskaźniku Relative Strength Index.