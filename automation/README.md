# Moduł Automatyzacji (Automation)

Ten katalog zawiera skrypty i narzędzia służące do automatyzacji procesów handlowych, takich jak codzienne wykonywanie zleceń, handel intraday oraz utrzymywanie sesji API.

## Kluczowe Pliki

- **`setup_auto.py`**: Interaktywny kreator konfiguracji (TUI) dla automatycznego handlu. Pozwala w prosty sposób ustawić strategię, alokację kapitału, limity ryzyka oraz tryb (LIVE/Paper) i zapisuje te ustawienia do pliku `daily_config.env`.
- **`run_daily.sh`**: Skrypt powłoki (bash) przygotowany do uruchamiania przez **cron**. Wczytuje konfigurację, aktywuje środowisko wirtualne i uruchamia `app.daily_trader` z odpowiednimi parametrami.
- **`run_intraday.sh`**: Odpowiednik powyższego skryptu dla handlu intraday (np. godzinowego). Uruchamia `app.intraday_trader`.
- **`keep_alive.py`**: Skrypt działający w tle, który cyklicznie odświeża token autoryzacyjny Saxo Banku, aby zapobiec wygaśnięciu sesji.

## Pliki Konfiguracyjne i Logi

- **`daily_config.env`**: Plik generowany przez `setup_auto.py`, zawierający parametry dla daily tradera (strategia, limity itp.).
- **`intraday_config.env`**: Plik konfiguracyjny dla handlu intraday.
- **`daily.log` / `intraday.log`**: Logi z wykonania skryptów automatycznych (stdout/stderr).

## Instrukcja Użycia

### 1. Konfiguracja Automatu

Przed uruchomieniem automatu, użyj kreatora, aby wygenerować poprawną konfigurację:

```bash
python automation/setup_auto.py
```

Otworzy się interfejs tekstowy, w którym możesz wybrać strategię, ustalić budżet i włączyć tryb wykonywania zleceń (Execution Mode).

### 2. Konfiguracja Cron (Linux)

Aby skrypty uruchamiały się automatycznie o określonych porach, dodaj wpisy do crontab (`crontab -e`):

```bash
# Przykład - Daily Trader codziennie o 16:55 (przed zamknięciem sesji GPW)
55 16 * * 1-5 /home/username/ZPRP/GPW-Quant-System/automation/run_daily.sh

# Przykład - Intraday Trader co godzinę w godzinach pracy giełdy (9-17)
0 9-17 * * 1-5 /home/username/ZPRP/GPW-Quant-System/automation/run_intraday.sh
```

> **Uwaga:** Upewnij się, że ścieżki w crontabie są absolutne i poprawne dla Twojego systemu.

### 3. Utrzymywanie Sesji (Keep Alive)

Aby token Saxo Banku nie wygasł (co uniemożliwiłoby działanie automatu), warto uruchomić skrypt `keep_alive.py` w tle, np. w sesji `tmux`, `screen` lub jako usługę systemd.

```bash
# Przykład - Uruchomienie w tle
python automation/keep_alive.py
```

Skrypt ten co 15 minut (domyślnie) odświeża token.
