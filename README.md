# GPW Quant System

System algorytmicznego tradingu dla Giełdy Papierów Wartościowych w Warszawie (GPW), zawierający moduły do pobierania danych, analizy ilościowej, backtestingu strategii i automatycznego handlu. System integruje się z Saxo Bank OpenAPI w celu realizacji zleceń handlowych i pobierania danych rynkowych w czasie rzeczywistym. Udostępnia również interfejs webowy do monitorowania i analizy wyników a także automatyczne wykonywanie zleceń handlowych na podstawie zdefiniowanych strategii. 

W zakresie projektu znajduje się implementacja kilku strategii inwestycyjnych, w tym autorskich modeli opartych na sieciach neuronowych (LSTM i Hybrid LSTM), a także klasycznych strategii technicznych (Momentum, Mean Reversion, RSI). W folderze `docs/` znajduje się dokumentacja techniczna oraz opisy zastosowanych strategii wraz z wynikami backtestów, analizami strategii w różnych warunkach rynkowych oraz porównaniami efektywności.

## Uruchomienie

### 1. Konfiguracja (założenie) konta Saxo Bank
Aby korzystać z handlu rzeczywistego lub pobierać dane live z Saxo Bank, musisz posiadać konto demo w Saxo Bank. 
1. Zarejestruj się na [Saxo Bank Developer Portal](https://www.developer.saxo/accounts/sim/signup).
2. [Utwórz aplikację](https://www.developer.saxo/openapi/appmanagement#/), aby uzyskać Client ID i Secret
3. Skonfiguruj swoją aplikację:
    - nazwa aplikacji według uznania
    - opis aplikacji według uznania
    - przekierowanie URI na np. `http://localhost:8765/oauth/callback` (ważne, aby podać port, mimo tego, że później nie podajemy go w pliku `.env`) w ustawieniach aplikacji Saxo
    - Grant Type: Code
    - Access Control: zaznaczamy flagę `Allow this app to be enabled for trading`
4. Stwórz plik `.env` w katalogu głównym projektu w oparciu o plik `.env.example`, dla systemu Linux/MacOS możesz użyć polecenia:
    ```bash
    cp .env.example .env
    ```

    *Ważne:* W pliku .env `APP_URL` musi być zgodny z tym, który podałeś podczas konfiguracji aplikacji w Saxo Bank **(nie podajemy portu**, dla przykładu powyżej będzie to `http://localhost/oauth/callback`).
5. Skopiuj App Key, App URL i dowolny z dwóch App Secret do pliku `.env`.
6. Uzyskanie Account Key nie jest tak oczywiste i niestety Saxo nie udostępnia go bezpośrednio w panelu deweloperskim. Aby go uzyskać:
    - wejdź na stronę [SaxoTrader](https://www.saxotrader.com/sim/login/en) i zaloguj się na swoje konto demo
    - przy pierwszym logowaniu należy skonfigurować swoje konto demo (ustawienia, waluta bazowa itp.) 
    - wybierz produkty inwestycyjne, które Cię interesują, jednak dla testów na GPW zalecamy wybór: CFD, akcje, ETF, opcje giełdowe
    - po zalogowaniu włącz narzędzia deweloperskie w przeglądarce (F12) i przejdź do zakładki "Network"
    - odśwież stronę (F5) i w filtrze wpisz `/v1/accounts` aby znaleźć odpowiednie żądanie
    - w odpowiedzi JSON znajdziesz pole `AccountKey`, które należy skopiować do pliku `.env` jako `SAXO_ACCOUNT_KEY` (uwaga: skopiuj bez cudzysłowów)

### 2. Konfiguracja środowiska
Poniższe kroki należy wykonywać z katalogu głównego projektu.
1. Stwórz i aktywuj wirtualne środowisko Pythona:
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate    # Windows
```
2. Upewnij się, że masz zainstalowane wymagane zależności:
```bash
pip install -r requirements.txt
```
3. Wykonaj skrypt pobierający dane historyczne z Stooq (dane GPW), przygotowujący sygnały wszystkich dostępnych strategii oraz uruchamiający backtesty i ich analizę, dostępną potem w dashboardzie webowym:
```bash
python -m data.scripts.setup_pipeline
```
### 3. Autoryzacja Saxo Bank
Aby korzystać z handlu rzeczywistego lub pobierać dane live z Saxo Bank:
1. Uruchom skrypt autoryzacyjny, aby wygenerować pierwszy token:
```bash
python -m data.scripts.saxo_auth login
```
Postępuj zgodnie z instrukcjami w terminalu (logowanie w przeglądarce).

### 4. Aplikacja Webowa (Dashboard)
System posiada interfejs webowy do analizy wyników backtestów i monitorowania systemu.

Uruchom serwer developerski:
```bash
python -m app.web
```
Dashboard będzie dostępny pod adresem: `http://localhost:5000`

Podczas logowania z aplikacji webowej, należy po kliknięciu przycisku logowania wejść w link 
wyświetlony w terminalu i zalogować się w wyświelonym oknie w przeglądarce. 

Fetchowanie danych z bieżącego dnia nie jest możliwe w godzinach otwarcia giełdy.
W przypadku próby synchronizacji danych z bieżącego dnia, system pobierze dane do "wczorajszego" dnia, 
a gdy te będą pobrane już wcześniej - nie wykona żadnej akcji.
## Struktura Projektu

> **Wskazówka:** Wszystkie poniższe katalogi zawierają własny plik `README.md` ze szczegółową dokumentacją techniczną.

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
