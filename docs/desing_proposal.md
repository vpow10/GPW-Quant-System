# ZPRP - Narzędzie do handlu algorytmicznego:  Design proposal


## Autorzy 
- Antoni Grajek 
- Michał Mokrzycki 324874
- Jan Szymczak 324894

### Cel i zakres

Celem jest implementacja serweru w Python, który wykorzystując wybrane algorytmy/strategie handlowe, umożliwia kupno/sprzedaż akcji na **Giełdzie papierów wartościowych w Warszawie (GPW)**, z realizacją zleceń na koncie demo przez **Saxo Bank OpenAPI**. <br>
System obejmuje: 
- badanie strategii (wraz z wykorzystaniem uczenia maszynowego)
- backtesty z uwzględnieniem prowizji
- raport z wynikami i kosztami wraz z interaktywnym UI stworzonym lokalnie jako strona webowa z użyciem Rest API

### Architektura wysokopoziomowa
- **data/** - pobieranie danych z API, czyszczenie, formatowanie, data engineering 
- **strategies/** - implementacja strategii, planowane:
    - **Momentum**
    - **Mean reversion**
    - Wykorzystanie ML jako filtr/sizer
    - Model regresyjny neuronowy 
- **backtest/** - backtesting strategii
- **execution/** - klient Saxo OpenAPI
- **reporting/** - skrypty raportujące
- **app/** - serwis wraz z web UI



### Plan wdrożenia

#### 21.10 – 24.10 – Konsultacje i poprawy zaproponowanego designu
- Doprecyzowanie wymagań projektowych.  
- Opracowanie wstępnej architektury systemu.  
- Podział projektu na moduły funkcjonalne.  

#### 24.10 – 02.11 – Przygotowanie prototypu (Proof of Concept)
- Implementacja podstawowego modułu `data`.  
- Opracowanie skryptu umożliwiającego pobranie danych z API.  
- Ustalenie formatu danych demo i złożenie zlecenia testowego przez Saxo API.  
- Weryfikacja komunikacji z API oraz poprawności struktury danych.  

#### 03.11 – 12.12 – Implementacja strategii oraz rozwój modułu `backtest`


##### Moduł `strategies` (03.11 – 12.11)
- Implementacja strategii **Momentum** – generowanie sygnałów w oparciu o siłę trendu cenowego.  
- Implementacja strategii **Mean Reversion** – identyfikacja odchyleń od wartości średnich i generowanie sygnałów powrotu do trendu.  
- Implementacja **filtra/sizera ML** – wykorzystanie modelu uczenia maszynowego do filtrowania sygnałów lub określania wielkości pozycji.  
- Utworzenie interfejsu bazowego `StrategyBase` umożliwiającego łatwą integrację nowych strategii.  
- Parametryzacja strategii i zapis wyników w ustandaryzowanym formacie danych (CSV/Parquet).  
- Testy jednostkowe poprawności generowania sygnałów.  

##### 13.11 – 12.12 – Utworzenie modułu `backtest`

- Tydzień 1 (13.11 – 17.11)  
Projekt architektury modułu, implementacja podstawowego silnika testowego, integracja z modułem `data`.

- Tydzień 2 (18.11 – 24.11)  
Obsługa typów zleceń, kosztów transakcyjnych i prowizji.

- Tydzień 3 (25.11 – 01.12)  
Dodanie poślizgu cenowego i kalendarza sesji GPW, testy działania silnika.

- Tydzień 4 (02.12 – 08.12)  
Obliczanie metryk efektywności i testy wydajności.

- Tydzień 5 (09.12 – 12.12)  
Walidacja strategii i porównanie wyników z benchmarkiem (WIG20).


#### 13.12 – 22.12 – Utworzenie serwisu i klienta (moduły `execution` i `app`)
- Integracja z API Saxo – wysyłanie i monitorowanie zleceń.  
- Implementacja obsługi kolejki zleceń i limitów.  
- Utworzenie serwera REST API do uruchamiania strategii i podglądu wyników w formie raportu i wykresów.  
- Utworzenie webowego UI przy pomocy Reacta lub django-bootstrap-ui 

- Testy integracyjne przepływu zleceń i poprawności odpowiedzi serwera.  

#### 23.12 – 27.12 – Przerwa świąteczna

#### 28.12 – 05.01 – Walidacja wyników i testy funkcjonalne
- Weryfikacja działania systemu w warunkach zbliżonych do rzeczywistych.  
- Testy integralności danych i komunikacji między modułami.  
- Ocena poprawności wykonania zleceń i spójności raportów.  

#### 06.01 – 12.01 – Dokumentacja i raport projektu
- Rozwój modułu `reporting` i generowanie końcowych raportów.  
- Opracowanie dokumentacji technicznej i instrukcji użytkownika
- Przygotowanie ostatecznej wersji projektu do oddania.  

#### 13.01 – Termin oddania projektu
- Przekazanie finalnej wersji systemu i raportu końcowego.
### Bibliografia
- Saxo OpenAPI: dokumentacja API, wszelkie potrzebne informacje o endpointach, typach danych. Link: https://www.developer.saxo/openapi/learn
- Podstawowe informacje o wykorzystywanych strategii. Link: https://investingoal.com/trading/best-strategies/ <br>
    - Momentum: najprościej ujmując strategia polegająca na wykorzystywaniu i analizowaniu trendów. Kupowane są akcje w trendzie wzrostowym, a sprzedawane są w momencie wyraźnego spadku trendu wzrostu lub jego odwróceniu. Strategia pozwala na względnie bezpieczne osiągnięcie stabilnych zysków, jednak jest podatna na wyraźne straty przy nagłych spadkach i zmianach na giełdzie.
    - Mean reversion: strategia opiera się na przekonaniu, że ceny akcji zwykle mają tendencję do powrotu do średniej ceny w pewnym określonym przeszłym oknie czasowym. Ogólnie strategia najlepiej sprawdza się w czasach względnej stagnacji na rynku, zdecydowanie gorzej wypada w okresie nagłych zmian i trendów.
- Artykuł naukowy badający wykorzystanie algorytmów genetycznych w strategiach handlowych na GPW. Paweł B. Myszkowski, Łukasz Rachwalski, Trading rule discovery on Warsaw Stock Exchange using coevolutionary algorithms, 2009, https://www.researchgate.net/publication/224089738_Trading_rule_discovery_on_Warsaw_Stock_Exchange_using_revolutionary_algorithms
Wykorzystanie uczenia maszynowego pozwala na zwiększenie osiąganych zysków, jednak predykcje uzyskiwane za jego pomocą powinny być wykorzystywane jako filtracja akcji, w które bezpieczniej jest inwestować, aniżeli opierać całe strategie tylko na predykcjach. Ponadto w przypadku giełdy wielkości GPW, która oferuje zdecydowanie mniejszą ilość dostępnych akcji względem np. NYSE, algorytmy mniej skomplikowane osiągają lepsze wyniki od bardziej złożonych z uwagi na wysokie ryzyko przetrenowania. Jednakże należy zwrócić uwagę, że artykuł powstał w 2009 roku, od tego czasu nastąpił znaczny rozwój strategii uczenia maszynowego w kierunku radzenia sobie z problemem zbyt małej ilości danych, powstały także algorytmy jak XGBoost, które dobrze sobie z tym problemem radzą, zatem w projekcie zbadana zostanie skuteczność nowszych algorytmów.
- Artykuł naukowy badający nowsze algorytmy uczenia maszynowego, Isaac Tonkin, Adrian Gepp, Geoff Harris, Bruce Vanstone, Benchmarking deep reinforcement learning approaches to trade execution, 2025, https://www.sciencedirect.com/science/article/pii/S0927538X25002136
W nawiązaniu do poprzedniego artykułu ten bada nowsze rozwiązania wykorzystania algorytmów uczenia maszynowego do osiągania zysków. Osiąganie najlepszych wyników wymaga jednak uważnej optymalizacji i dostosowania parametrów uczenia nadzorowanego.



