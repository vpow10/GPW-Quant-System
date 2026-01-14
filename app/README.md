# Moduł Aplikacji (App)

Katalog ten zawiera główną logikę biznesową systemu, w tym interfejsy użytkownika (Web oraz TUI) oraz silniki wykonywania transakcji (Execution Engines).

## Kluczowe Pliki

Oto opis najważniejszych komponentów w tym module:

- **`web.py`**: Serwer aplikacji webowej oparty na frameworku Flask. Obsługuje Dashboard dostępny w przeglądarce oraz wystawia endpointy API dla frontendu.
- **`daily_trader.py`**: Główny skrypt do handlu w interwale dziennym (Daily Trading). Odpowiada za pobieranie danych, generowanie sygnałów na podstawie strategii, obliczanie wielkości pozycji oraz (opcjonalnie) składanie zleceń w Saxo Banku.
- **`app.py`**: Aplikacja TUI (Text User Interface) zbudowana w bibliotece `Textual`. Służy do szybkiego, ręcznego składania zleceń i podglądu rynku z poziomu terminala.
- **`dashboard.py`**: Alternatywny Dashboard w formie TUI (Textual), umożliwiający monitorowanie stanu konta i systemu bezpośrednio w terminalu.
- **`intraday_trader.py`**: Moduł do handlu intraday (na świecach godzinowych).
- **`engine.py`**: Warstwa logiki biznesowej łącząca klienta Saxo Banku z logiką strategii inwestycyjnych.
- **`sync.py`**: Narzędzia do synchronizacji danych między lokalną bazą a zewnętrznymi źródłami (Saxo, GPW).

## Instrukcja Użycia

### 1. Uruchomienie Web Dashboardu

Aby uruchomić interfejs webowy do monitorowania systemu i analizy wyników:

```bash
# Uruchamia serwer na http://localhost:5000
python -m app.web
```

### 2. Uruchomienie Daily Tradera

Skrypt ten jest zazwyczaj uruchamiany automatycznie przez crona (`automation/run_daily.sh`), ale można go wywołać ręcznie:

```bash
# Tryb symulacji (Dry Run) - tylko logowanie, bez składania zleceń
python -m app.daily_trader --strategy rsi_14d_basic --allocation-pct 0.1

# Tryb rzeczywisty (LIVE) - SKŁADA ZLECENIA NA RYNKU
python -m app.daily_trader --strategy rsi_14d_basic --allocation-pct 0.1 --execute
```

### 3. Uruchomienie TUI Dashboardu

Jeśli wolisz interfejs tekstowy w terminalu:

```bash
python -m app.dashboard
```

### 4. Narzędzie do składania zleceń (TUI)

Aby szybko złożyć zlecenie ręcznie z poziomu terminala:

```bash
python -m app.app
```

## Konfiguracja

Upewnij się, że w głównym katalogu projektu znajduje się plik `.env` zawierający niezbędne klucze API Saxo Banku:

- `SAXO_URL`
- `SAXO_APP_KEY`
- `SAXO_APP_SECRET`
- `SAXO_AUTH_ENDPOINT`
- `SAXO_TOKEN_ENDPOINT`
