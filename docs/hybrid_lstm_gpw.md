# Strategia Hybrid LSTM (GPW) – dokumentacja techniczna

## 1. Cel i zakres

Strategia Hybrid LSTM RegimeBlend jest strategią generowania sygnałów transakcyjnych dla akcji z GPW (oraz indeksu referencyjnego WIG20), w której predykcja oparta o uczenie maszynowe jest łączona z regułami portfelowymi zależnymi od reżimu rynku.

W ujęciu implementacyjnym strategia:
- trenuje oddzielny model dla każdej spółki (supervised learning),
- predykuje logarytmiczną stopę zwrotu w horyzoncie 10 dni,
- zamienia predykcje na przekrojowy ranking (z-score) w danym dniu,
- generuje sygnał long/short/flat z histerezą wejścia/wyjścia i minimalnym czasem utrzymania,
- stosuje filtr reżimów i zmienności WIG20, który modyfikuje dozwolone pozycje oraz ekspozycję.

Dokument opisuje: przepływ danych, inżynierię cech, uczenie modelu, logikę sygnału, parametry sterujące oraz wnioski eksperymentalne.

---

## 2. Artefakty i pliki

Najważniejsze moduły (nazwy jak w kodzie źródłowym):

### 2.1. Strategia i cechy
- `hybrid_lstm_strategy.py` – docelowa strategia (interfejs `StrategyBase`), logika budowy sygnału, reżimy i filtry WIG20.
- `hybrid_features.py` – definicje cech, targetu, dołączanie WIG20 oraz wczytywanie sygnałów bazowych.
- `indicators.py` – implementacje RSI i TSI używane w cechach.

### 2.2. Modele i narzędzia uczenia
- `NNmodels.py` – architektura `HybridLSTM` oraz `RegimeGatedModel` (bramka reżimu).
- `lstm_utils.py` – `TimeSeriesScaler` (standaryzacja Z-score + zapis/odczyt JSON).
- `train_hybrid_lstm.py` – trening modeli per symbol, zapis checkpointów i scalerów.
- `build_hybrid_lstm_signals.py` – inferencja i budowa pliku parquet z predykcjami oraz sygnałem strategii.

### 2.3. Strategie bazowe (źródła `mom_signal` i `mr_signal`)
- `momentum.py` – strategia momentum (trend-following) generująca sygnał `signal`.
- `mean_reversion.py` – strategia mean-reversion generująca sygnał `signal`.

### 2.4. Backtest i uruchomienie
- `engine.py` – silnik backtestu (`BacktestEngine`, koszty, tryb single/portfolio).
- `run_backtest.py` – CLI do uruchamiania backtestu i zapisu wyników.
- `base.py` – interfejs strategii (kontrakt na `generate_signals` i metadane).

---
## 3. Dane wejściowe

### 3.1. Format wejścia (panel dzienny)

Wszystkie funkcje pracują na „panelu” danych dziennych o postaci tabelarycznej, gdzie każda obserwacja jest parą `(symbol, date)`.

**Minimalny zestaw kolumn wymagany do wygenerowania cech:**
- identyfikacja: `symbol` (string), `date` (datetime),
- ceny i wolumen: `open`, `high`, `low`, `close`, `volume`,
- zwrot dzienny: `ret_1d` (float), interpretowany jako `close/close[-1] − 1`.

Dodatkowo panel powinien zawierać wiersze dla indeksu WIG20 jako osobny instrument o symbolu równym `wig20_symbol` (domyślnie `"wig20"`), aby możliwe było wyliczenie cech reżimu i filtrów. W naszym przypadku WIG20 jest traktowany jako „benchmark” rynku akcji. Do pobrania danych wykorzystywany jest skrypt `data/scripts/stooq_fetch.py` wraz z `data/scripts/preprocess_gpw.py`, który generuje plik `data/processed/gpw/[symbol].parquet` dla każdej spółki oraz `data/processed/gpw/wig20.parquet` dla indeksu.

### 3.2. Zewnętrzne sygnały bazowe (tabular)

Strategia wykorzystuje dwa sygnały dyskretne, dołączane jako cechy tabular:

- `mom_signal` – sygnał momentum (trend-following),
- `mr_signal` – sygnał mean-reversion (odchylenie od średniej).

W implementacji są one wczytywane z plików:
- `data/signals/momentum.parquet`,
- `data/signals/mean_reversion.parquet`,

i scalane z panelem na kluczach `(symbol, date)`.

#### 3.2.1. Momentum (`MomentumStrategy`)

Definicja cechy pomocniczej:
- `momentum_t = close_t / close_{t-lookback} - 1`.

Reguła sygnału:
- LONG (`+1`), gdy `momentum_t > entry_long`,
- SHORT (`−1`), gdy `momentum_t < entry_short`,
- FLAT (`0`) w pozostałych przypadkach.

Parametry i ich wpływ:
- `lookback` (int) – horyzont oceny trendu; większy wygładza i opóźnia reakcję,
- `entry_long`, `entry_short` (float) – progi wejścia; większe wartości redukują liczbę transakcji i zwiększają „selektywność”,
- `long_only`, `short_only` – ograniczenia kierunkowe (wymuszają odpowiednio {0,1} lub {0,−1}).

#### 3.2.2. Mean-reversion (`MeanReversionStrategy`)

Definicje:
- `ma_t` – średnia krocząca z `window`,
- `std_t` – odchylenie standardowe z `window`,
- `zscore_t = (close_t − ma_t) / std_t`.

Reguła sygnału:
- LONG (`+1`), gdy `zscore_t < −z_entry` (cena istotnie poniżej średniej),
- SHORT (`−1`), gdy `zscore_t > +z_entry` (cena istotnie powyżej średniej),
- FLAT (`0`) w pozostałych przypadkach.

Parametry i ich wpływ:
- `window` (int) – długość okna estymacji; większa stabilizuje średnią/odchylenie kosztem opóźnienia,
- `z_entry` (float) – próg „oddalenia”; większy próg oznacza rzadsze, bardziej ekstremalne sygnały,
- `long_only`, `short_only` – ograniczenia kierunkowe analogicznie jak wyżej.

#### 3.2.3. Rola sygnałów bazowych w Hybrid LSTM

`mom_signal` i `mr_signal` są:
1) wejściami do gałęzi tabular modelu (uczenie nadzorowane),
2) wykorzystywane w warstwie decyzyjnej:
   - `mom_signal` jest dodatkowo normalizowany przekrojowo (`mom_z`) i może być mieszany z predykcją modelu w reżimie BULL (parametr `bull_score_blend`).

Uwaga praktyczna: ponieważ `mom_signal` i `mr_signal` są dyskretne (−1/0/+1), ich przekrojowe z-score ma charakter skokowy (wiele obserwacji ma identyczną wartość), co ogranicza „rozdzielczość” rankingu.

---
## 4. Inżynieria cech

### 4.1. Definicje wskaźników

- **RSI (Relative Strength Index)**: liczony ze zmian ceny w oknie `window` (domyślnie 14), klasyczna definicja oparta o średnie wzrosty i spadki.
- **TSI (True Strength Index)**: wskaźnik momentum z podwójnym wygładzaniem EMA (parametry `r=25`, `s=13`).

### 4.2. Cechy instrumentu (per spółka)

Funkcja `add_stock_indicators()` buduje zestaw cech:
- transformacje zwrotu i wolumenu:
  - `ret_1d_log = log(1 + ret_1d)`,
  - `vol_log = log(volume)`, `vol_log_chg = Δ(vol_log)`,
- wskaźniki i ryzyko:
  - `rsi_14`, `tsi`, `vol_20d` (odchylenie std. `ret_1d_log` z 20 dni),
  - średnie kroczące `ma_20`, `ma_50` oraz relacje `price_ma20_ratio`, `price_ma50_ratio`,
  - `atr_14` oraz `atr14_rel = atr_14 / close`,
  - `beta_60d` względem WIG20 (rolling cov/var na 60 dni), jeśli dostępna jest seria `wig20_ret_1d`.

### 4.3. Cechy sekwencyjne (dla LSTM)

Sekwencja ma długość **LAGS = 24**. Dla każdego dnia model otrzymuje macierz o wymiarach:
- **(LAGS, SEQ_INPUT_SIZE)**, gdzie `SEQ_INPUT_SIZE = 4` (liczba grup cech).

Cztery grupy wejść sekwencyjnych zawierają opóźnienia (lag1…lag24) następujących szeregów:
1. `log_return_lag*` – opóźnione `ret_1d_log`,
2. `log_vol_chg_lag*` – opóźnione `vol_log_chg`,
3. `rsi_14_lag*` – opóźnione `rsi_14`,
4. `tsi_lag*` – opóźnione `tsi`.

W praktyce: dla danego dnia „t” model widzi 24‑dniową historię tych czterech kanałów.

### 4.4. Cechy tabular (statyczne dla dnia)

Zbiór `TAB_FEATURES` zawiera 10 zmiennych (dla danego dnia):
- `mom_signal`, `mr_signal`,
- cechy WIG20: `wig20_ret_1d`, `wig20_mom_60d`, `wig20_vol_20d`, `wig20_rsi_14`,
- miary trendu/ryzyka i relacji do rynku: `price_ma20_ratio`, `price_ma50_ratio`, `atr14_rel`, `beta_60d`.

Intuicyjnie: tabular dopina do „historii” LSTM bieżący kontekst trendu, ryzyka i relatywnej ekspozycji na rynek.

### 4.5. Cechy reżimu (dla modułu gating)

Zbiór `REGIME_FEATURES` zawiera cechy makro‑kontekstu rynku:
- `wig20_mom_60d`,
- `wig20_vol_20d`,
- `wig20_rsi_14`.

Te cechy są wejściem do komponentu **RegimeGatedModel**, który ma modulować (gating) zachowanie predyktora w zależności od stanu rynku.

---

## 5. Zmienna objaśniana (target)

Model uczy się przewidywać:
- `TARGET_HORIZON = 10`,
- `TARGET = ret_10d_log = log(close[t+10] / close[t])`.

Jest to logarytmiczna stopa zwrotu forward w horyzoncie 10 sesji. W trakcie treningu dane z końca szeregu (gdzie `close[t+10]` jest nieznane) są odrzucane przez `dropna`.

---

## 6. Model hybrydowy: struktura i uczenie

### 6.1. Architektura (zgodna z implementacją)

Model jest hybrydą dwóch torów cech oraz bramki reżimowej:

1. **Tor sekwencyjny (LSTM)** – przetwarza historię cech w oknie `LAGS`.
2. **Tor tabular (MLP)** – przetwarza cechy jednowymiarowe dla danego dnia (sygnały bazowe, WIG20, itp.).
3. **Bramka reżimu (MLP + sigmoid)** – na podstawie cech WIG20 wyznacza współczynnik w zakresie `[0, 1]`, którym mnożona jest predykcja modelu bazowego.

#### 6.1.1. `HybridLSTM` (model bazowy)

Wejścia:
- `seq_x ∈ R^{B×L×d_seq}` – sekwencja długości `L` (LAGS) o wymiarze cech `d_seq`,
- `tab_x ∈ R^{B×d_tab}` – wektor cech tabular.

Kroki obliczeń:
- `seq_out = LSTM(seq_x) ∈ R^{B×L×h}`,
- `seq_last = seq_out[:, −1, :] ∈ R^{B×h}` (ostatni krok sekwencji),
- `tab_feat = MLP_tab(tab_x) ∈ R^{B×d_h}`,
- konkatenacja: `x = [seq_last ; tab_feat] ∈ R^{B×(h+d_h)}`,
- `pred = MLP_head(x) ∈ R^{B×1}`.

Istotne hiperparametry:
- `lstm_hidden` (`h`) – liczba jednostek ukrytych LSTM (zwiększa pojemność modelu, ale rośnie ryzyko przeuczenia),
- `lstm_layers` – liczba warstw LSTM; dropout w LSTM jest aktywny tylko dla `lstm_layers > 1`,
- `tab_hidden` (`d_h`) – szerokość MLP tabular,
- `head_hidden` – szerokość „głowy” regresyjnej po konkatenacji,
- `dropout` – regularizacja w MLP tabular i w głowie (oraz w LSTM, jeśli `lstm_layers > 1`).

#### 6.1.2. `RegimeGatedModel` (bramka reżimu)

Wejście:
- `regime_x ∈ R^{B×d_reg}` – cechy reżimu (w praktyce: wybrane cechy WIG20).

Kroki obliczeń:
- `base_pred = HybridLSTM(seq_x, tab_x) ∈ R^{B×1}`,
- `gate = sigmoid(MLP_regime(regime_x)) ∈ (0, 1)`,
- wynik: `pred = base_pred · gate`.

Interpretacja:
- bramka pełni rolę ciągłej modulacji ekspozycji predykcyjnej: jeśli `gate` jest małe, amplituda predykcji jest tłumiona (model „przygasza” sygnał w niekorzystnym stanie rynku); jeśli `gate` jest bliskie 1, predykcja przechodzi prawie bez zmian.

Ważne rozróżnienie:
- bramka reżimu działa wewnątrz modelu predykcyjnego,
- filtr reżimowy WIG20 opisany w sekcji 7 i 10 działa na etapie zamiany predykcji na sygnał transakcyjny (reguły long-only / flat / vol-quantile).

---
### 6.2. Standaryzacja wejść

Dla stabilności uczenia i porównywalności skali zmiennych stosowane są trzy niezależne standaryzacje typu Z-score:

- `seq_scaler` – dla cech sekwencyjnych po spłaszczeniu do macierzy `R^{N×(L·d_seq)}`,
- `tab_scaler` – dla cech tabular `R^{N×d_tab}`,
- `reg_scaler` – dla cech reżimu `R^{N×d_reg}`.

Mechanizm standaryzacji (`TimeSeriesScaler`):
- estymuje `mean` i `std` (odchylenie populacyjne, `ddof=0`) po osi obserwacji,
- transformuje: `X_scaled = (X − mean) / std`,
- dla kolumn o zerowej wariancji wymusza `std = 1`, aby uniknąć dzielenia przez zero,
- zapisuje/odczytuje parametry do/z JSON (listy `mean` i `scale`).

Zasada poprawności metodologicznej:
- każdy scaler jest fitowany wyłącznie na zbiorze treningowym i następnie używany do transformacji walidacji/testu oraz do inferencji out-of-sample.

Efekt zmian:
- brak standaryzacji zwykle prowadzi do dominacji cech o dużej skali (np. wolumen) i utrudnia optymalizację,
- zbyt agresywna standaryzacja (np. fit na całym zbiorze) skutkuje „przeciekiem informacji” (data leakage) i zawyżeniem wyników testu.

---
### 6.3. Procedura treningu (per symbol)

Skrypt `train_hybrid_lstm.py` wykonuje dla każdej spółki:
1. filtr czasowy: uczenie wyłącznie na danych przed 2020‑01‑01 (`TRAIN_END_DATE`),
2. przygotowanie cech i targetu, odrzucenie braków (`dropna`),
3. podział sekwencyjny na:
   - test: ostatnie 20% obserwacji,
   - z pozostałych: walidacja 15% (relatywnie do 80%),
   - reszta: trening,
4. uczenie z:
   - `SmoothL1Loss` (Huber),
   - `Adam` z `lr = 1e−3`,
   - `batch_size = 64`,
   - maks. `400` epok,
   - wczesnym stopem z cierpliwością `40` epok (na stracie walidacyjnej).

Po treningu zapisywany jest:
- checkpoint modelu: `{sym}_hybrid_lstm.pth`,
- scalery: `{sym}_seq_scaler.json`, `{sym}_tab_scaler.json`, `{sym}_reg_scaler.json`.

---

## 7. Inferencja i budowa sygnałów transakcyjnych

### 7.1. Predykcja per spółka

Dla każdej spółki:
1. wczytanie modelu i scalerów,
2. obliczenie cech instrumentu i cech WIG20,
3. budowa tensora sekwencyjnego i wektorów tabular/regime,
4. transformacja scalerami,
5. forward pass → `hybrid_pred`.

### 7.2. Wygładzanie predykcji

Parametr `z_smooth_span` (domyślnie 10) włącza wygładzanie:
- `hybrid_pred_s = EWMA(hybrid_pred, span=z_smooth_span)` per symbol.

Efekt:
- większy span → mniejszy szum i obrót, ale większe opóźnienie sygnału,
- span=0 → brak wygładzania.

### 7.3. Przekrojowa normalizacja (ranking)

W danym dniu `date` strategia liczy:
- `pred_z` = z-score przekrojowy predykcji `hybrid_pred_s` po wszystkich spółkach,
- `mom_z` = z-score przekrojowy sygnału `mom_signal`.

Z-score jest liczony jako `(x − mean) / std` na przekroju danego dnia; w przypadku `std=0` zwracane jest `0`.

Konsekwencja: sygnał jest relatywny, a nie absolutny – model służy do selekcji najlepszych/najsłabszych spółek w danym dniu.

### 7.4. Reżimy rynku (filtr WIG20)

Reżim jest definiowany na podstawie znaku `wig20_mom_60d`:
- `BULL` gdy `wig20_mom_60d > 0`,
- `BEAR` gdy `wig20_mom_60d < 0`,
- `NORMAL` w przeciwnym razie ($\approx$ momentum bliskie zera).

### 7.5. Blend score w hossie (RegimeBlend)

W reżimie `BULL` budowany jest wynik mieszany:
- `score_z = (1 − w) * pred_z + w * mom_z`,
- gdzie `w = bull_score_blend` (domyślnie 0.6).

Dla `NORMAL` i `BEAR` domyślnie `score_z = pred_z`.

Interpretacja parametru `bull_score_blend`:
- `0` → wyłącznie predykcja modelu (pred_z),
- `1` → wyłącznie momentum (mom_z),
- wartości pośrednie → kompromis „ML vs trend”.

### 7.6. Harmonogram rebalansu

Parametr `rebalance` określa kiedy strategia może zmienić pozycję:
- `daily` → decyzja codziennie,
- `weekly` → decyzja tylko w dniu tygodnia `rebalance_weekday` (0=pon … 4=pt).

Poza dniami rebalansu pozycja jest utrzymywana (brak wejść/wyjść).

### 7.7. Logika wejścia/wyjścia (histereza + min-hold)

Dla każdej spółki działa automat stanów z pozycją `pos ∈ {−1, 0, +1}`.

Na dniach rebalansu:
- **Wejście** z pozycji 0:
  - jeśli `score_z > z_entry` → `pos = +1`,
  - jeśli `score_z < −z_entry` → `pos = −1`.
- **Wyjście** z pozycji ±1 (dopiero po spełnieniu `min_hold_days`):
  - jeśli `pos=+1` i `score_z < z_exit` → `pos = 0`,
  - jeśli `pos=−1` i `score_z > −z_exit` → `pos = 0`.

Parametry `z_entry` i `z_exit` tworzą histerezę (zwykle `z_entry > z_exit`), co stabilizuje pozycje i ogranicza „przeskakiwanie” na granicy progu.

Parametr `min_hold_days` wymusza minimalny czas utrzymania pozycji (w dniach) i redukuje obrót.

### 7.8. Filtr zmienności WIG20 (vol-quantile)

Strategia wyznacza progi zmienności na bazie rozkładu `wig20_vol_20d`:
- `vol_q_bull = quantile(wig20_vol_20d, bull_vol_quantile)`,
- `vol_q_norm = quantile(wig20_vol_20d, normal_vol_quantile)`,
- `vol_q_bear = quantile(wig20_vol_20d, bear_vol_quantile)`.

Następnie w danym dniu, zależnie od reżimu, jeśli `wig20_vol_20d` przekracza odpowiedni próg, sygnał jest zerowany (`signal = 0`).

Intuicja: jest to filtr typu „risk-off” w okresach wysokiej zmienności rynku.

### 7.9. Ograniczenia reżimowe (long-only / flat / short-only)

Po zbudowaniu sygnału bazowego stosowane są ograniczenia zależne od reżimu:
- `bull_long_only=True` → w `BULL` shorty są wyłączone (sygnał <0 → 0),
- `normal_long_only=True` → w `NORMAL` shorty wyłączone,
- `bear_flat=True` → w `BEAR` wszystko w gotówkę (sygnał → 0),
- `bear_short_only=True` → w `BEAR` dopuszczalne wyłącznie shorty (long → 0); ignorowane, jeśli `bear_flat=True`.

---

## 8. Wyjścia strategii

Metoda `generate_signals(df)` zwraca DataFrame wejściowy wzbogacony m.in. o:
- `signal` ∈ {−1,0,+1} – docelowy sygnał pozycji,
- `prev_signal` – sygnał z dnia poprzedniego (pomocne do liczenia obrotu),
- predykcje i diagnostyka:
  - `hybrid_pred`, `hybrid_pred_s`,
  - `pred_z`, `mom_z`, `score_z`,
  - `regime`.

Dodatkowo `StrategyBase` dopina metadane:
- `strategy` – nazwa strategii,
- `params` – parametry strategii jako string.

---

## 9. Parametry sterujące (konfiguracja)

Konfiguracja jest zdefiniowana w `HybridLSTMRegimeBlendConfig` i przekazywana w konstruktorze strategii.

| Parametr | Domyślnie | Rola | Główny efekt zmiany |
|---|---:|---|---|
| `models_dir` | `models/hybrid_lstm` | katalog z checkpointami i scalerami | inny zestaw modeli / środowisko |
| `wig20_symbol` | `wig20` | symbol instrumentu indeksowego w panelu | zmiana benchmarku/filtra reżimu |
| `z_entry` | 1.0 | próg wejścia (z-score) | większy → mniej transakcji, silniejsza selekcja; mniejszy → więcej pozycji/obrót |
| `z_exit` | 0.3 | próg wyjścia (z-score) | większy → szybsze wychodzenie; mniejszy → dłuższe trzymanie |
| `min_hold_days` | 10 | min. czas utrzymania | większy → mniejszy obrót, większe ryzyko „przetrzymania”; mniejszy → większa reaktywność |
| `z_smooth_span` | 10 | EWMA predykcji | większy → gładszy sygnał i mniejszy obrót kosztem opóźnienia |
| `rebalance` | weekly | częstotliwość decyzji | weekly zwykle redukuje koszty; daily zwiększa adaptację i obrót |
| `rebalance_weekday` | 4 (pt) | dzień tygodnia rebalansu | steruje „kalendarzem” wejść/wyjść przy weekly |
| `bull_long_only` | True | blokada shortów w BULL | zwykle podnosi beta i zmniejsza ryzyko przeciw trendowi |
| `bear_flat` | True | gotówka w BEAR | silna kontrola obsunięcia, ale ryzyko utraty zysków z shortów |
| `bear_short_only` | False | short-only w BEAR | ekspozycja na spadki; większe ryzyko squeezów i kosztów |
| `normal_long_only` | False | blokada shortów w NORMAL | ogranicza ekspozycję na short, zmniejsza ryzyko idiosynkratyczne |
| `bull_vol_quantile` | 1.0 | filtr vol w BULL | 1.0 wyłącza; niżej → częściej `signal=0` przy wysokiej zmienności |
| `normal_vol_quantile` | 0.7 | filtr vol w NORMAL | niżej → mniejsza ekspozycja, potencjalnie niższe DD i niższy CAGR |
| `bear_vol_quantile` | 0.7 | filtr vol w BEAR | istotne tylko, gdy `bear_flat=False` |
| `bull_score_blend` | 0.6 | mieszanie pred_z i mom_z w BULL | wyżej → bardziej trend-following w hossie |
| `universe` | None | lista symboli | w tej klasie przechowywana konfiguracyjnie; selekcja zwykle realizowana upstream |

---

## 10. Mechanizm filtra WIG20

WIG20 jest w strategii wykorzystywany równolegle w trzech rolach: jako źródło cech, jako wejście do bramki reżimu w modelu oraz jako sygnał do reguł „risk management” na etapie decyzyjnym.

### 10.1. Konstrukcja cech WIG20 i dołączenie do panelu

Funkcja `add_wig20_features()` buduje dla indeksu WIG20 (wymagane, aby panel zawierał wiersze `symbol == wig20_symbol`) następujące serie:

- `wig20_ret_1d` – dzienny zwrot procentowy,
- `wig20_mom_60d` – suma `wig20_ret_1d` z 60 sesji (proxy trendu),
- `wig20_vol_20d` – odchylenie standardowe `wig20_ret_1d` z 20 sesji (proxy ryzyka/zmienności),
- `wig20_rsi_14` – RSI z 14 sesji.

Cechy są następnie dołączane do wszystkich spółek po dacie (`merge` na `date`). W praktyce oznacza to, że każda obserwacja `(symbol, date)` ma również „kontekst rynkowy” z WIG20.

### 10.2. WIG20 jako wejście do modelu (część ML)

Cechy WIG20 wchodzą do dwóch wektorów:

- `TAB_FEATURES` (tor tabular): m.in. `wig20_ret_1d`, `wig20_mom_60d`, `wig20_vol_20d`, `wig20_rsi_14`.
- `REGIME_FEATURES` (tor bramki): `wig20_mom_60d`, `wig20_vol_20d`, `wig20_rsi_14`.

W efekcie predykcja `ret_10d_log` jest funkcją nie tylko historii spółki i sygnałów bazowych, ale również bieżącego stanu rynku.

### 10.3. Reżim rynku jako reguła portfelowa (poza modelem)

Po uzyskaniu predykcji modelu strategia nadaje etykietę reżimu na podstawie znaku trendu WIG20:

- `BULL`, gdy `wig20_mom_60d > 0`,
- `BEAR`, gdy `wig20_mom_60d < 0`,
- `NORMAL` w pozostałych przypadkach.

Reżim wpływa na:
- możliwość blendowania `score_z` w BULL (`bull_score_blend`),
- ograniczenia kierunkowe (np. `bull_long_only`, `bear_flat`, `bear_short_only`, `normal_long_only`).

### 10.4. Filtr zmienności WIG20 (vol-quantile)

Dodatkowo strategia może wyzerować sygnał w okresach „risk-off” na podstawie zmienności WIG20:

1) wyznaczane są progi kwantylowe `vol_q_*` na serii `wig20_vol_20d`,
2) dla każdej obserwacji sprawdzane jest `wig20_vol_20d <= vol_q_{regime}`,
3) jeśli warunek nie jest spełniony, to `signal` jest ustawiany na `0`.

Parametry:
- `bull_vol_quantile`, `normal_vol_quantile`, `bear_vol_quantile` – im niższy kwantyl, tym bardziej restrykcyjny filtr (więcej dni wyłączonych).

### 10.5. Relacja: bramka reżimu vs filtr reżimu

- **Bramka reżimu (`RegimeGatedModel`)**: ciągła modulacja predykcji na poziomie modelu (mnożenie przez `gate ∈ [0,1]`).
- **Filtr reżimu WIG20**: dyskretne reguły po predykcji (klasa reżimu, long-only/flat, vol-quantile).

W praktyce oba mechanizmy mogą działać komplementarnie: model może „przygaszać” sygnał w trudnych warunkach, a filtr może dodatkowo blokować transakcje w dniach o podwyższonej zmienności lub wymuszać ograniczenia kierunkowe.

---
## 11. Uruchomienie: przygotowanie sygnałów, trening, inferencja

Pipeline zakłada następującą kolejność:
1) przygotowanie panelu `combined.parquet` (z wierszami dla WIG20),
2) wygenerowanie sygnałów bazowych (`momentum.parquet`, `mean_reversion.parquet`),
3) trening modeli per symbol,
4) inferencja i budowa sygnału Hybrid LSTM do pliku parquet,
5) backtest (single lub portfolio).

### 11.1. Dane wejściowe

Skrypty `train_hybrid_lstm.py` i `build_hybrid_lstm_signals.py` oczekują pliku:
- `data/processed/reports/combined.parquet`.

Ważne wymagania:
- kolumny minimalne: `symbol`, `date`, `open`, `high`, `low`, `close`, `volume`, `ret_1d`,
- panel powinien zawierać instrument WIG20 pod nazwą zgodną z `wig20_symbol` (domyślnie `"wig20"`), aby dało się policzyć cechy reżimu.

### 11.2. Generowanie sygnałów bazowych

Sygnały `mom_signal` i `mr_signal` są ładowane z:
- `data/signals/momentum.parquet`,
- `data/signals/mean_reversion.parquet`.

W repozytorium dostarczone są definicje strategii bazowych (`MomentumStrategy`, `MeanReversionStrategy`), ale sposób uruchamiania może być dowolny. Minimalny schemat (Python) wygląda następująco:

```python
import pandas as pd
from strategies.momentum import MomentumStrategy
from strategies.mean_reversion import MeanReversionStrategy

panel = pd.read_parquet("data/processed/reports/combined.parquet")

mom = MomentumStrategy(lookback=5, entry_long=0.05, entry_short=-0.05)
mr = MeanReversionStrategy(window=20, z_entry=1.5)

mom_df = mom.generate_signals(panel)
mr_df = mr.generate_signals(panel)

mom_df[["symbol","date","signal"]].to_parquet("data/signals/momentum.parquet")
mr_df[["symbol","date","signal"]].to_parquet("data/signals/mean_reversion.parquet")
```

### 11.3. Trening

Modele uczone są per symbol przez `train_hybrid_lstm.py`. Skrypt zapisuje:
- checkpoint modelu `models/hybrid_lstm/{sym}_hybrid_lstm.pth`,
- trzy scalery `*_seq_scaler.json`, `*_tab_scaler.json`, `*_reg_scaler.json`.

### 11.4. Generowanie sygnałów Hybrid LSTM (CLI)

Skrypt `build_hybrid_lstm_signals.py` buduje plik parquet z:
- predykcjami (`hybrid_pred`),
- z-score (`pred_z`, `mom_z`, `score_z`),
- reżimem (`regime`),
- sygnałem końcowym (`signal`, `prev_signal`).

Przykład użycia:

```bash
python build_hybrid_lstm_signals.py   --output data/signals/hybrid_lstm.parquet   --models-dir models/hybrid_lstm   --wig20-symbol wig20   --z-entry 0.7   --z-exit 0.3   --min-hold-days 10   --z-smooth-span 10   --rebalance weekly   --rebalance-weekday 4   --bull-vol-quantile 1.0   --normal-vol-quantile 0.7   --bear-vol-quantile 0.7   --bull-score-blend 0.0
```

### 11.5. Backtest (CLI)

Backtest uruchamia się przez `run_backtest.py`. Przykład trybu portfelowego:

```bash
python run_backtest.py   --signals data/signals/hybrid_lstm.parquet   --mode portfolio   --initial-capital 100000   --commission-bps 5   --slippage-bps 5   --benchmark data/benchmarks/wig20.parquet
```

W trybie `single` należy dodatkowo podać `--symbol`.

---
## 12. Backtest i ewaluacja wyników

Warstwa backtestu jest rozdzielona od strategii: strategia produkuje sygnał kierunkowy `signal ∈ {−1, 0, +1}`, a silnik backtestu mapuje go na wagi portfela, liczy zwroty oraz koszty.

### 12.1. Konfiguracja (`BacktestConfig`)

Parametry:
- `initial_capital` (PLN) – kapitał początkowy,
- `commission_bps` – prowizja brokera w punktach bazowych (bps) **per strona transakcji**,
- `slippage_bps` – poślizg cenowy w bps **per strona transakcji**,
- `max_gross_leverage` – limit dźwigni brutto w trybie portfelowym,
- `trading_days_per_year` – konwencja do annualizacji (domyślnie 252).

Łączny koszt jednostkowy obrotu:
- `cost_per_turnover = (commission_bps + slippage_bps) / 10_000`.

### 12.2. Założenie anty-lookahead

Sygnał z dnia *T* nie może wpływać na transakcję w tym samym dniu.
Silnik realizuje to poprzez opóźnienie wagi:
- `weight_lag1 = weight.shift(1)`,

a zwrot dzienny liczony jest jako:
- `gross_ret_T = ret_1d_T · weight_lag1_T`.

W praktyce oznacza to: **sygnał wygenerowany na zamknięciu dnia T jest realizowany od dnia T+1**.

### 12.3. Tryb pojedynczego instrumentu (`run_single_symbol`)

Mapowanie sygnału na wagę:
- `weight = clip(signal, −1, +1)`.

Definicje:
- obrót (turnover): `|weight_T − weight_{T−1}|`,
- koszt w stopie zwrotu: `cost_ret = turnover · cost_per_turnover`,
- zwrot netto: `net_ret = gross_ret − cost_ret`,
- krzywa kapitału: `equity_T = initial_capital · Π(1 + net_ret)`.

Metryki:
- `ann_return`, `ann_vol`, `sharpe` (bez stopy wolnej od ryzyka),
- `max_drawdown` z krzywej kapitału.

### 12.4. Tryb portfelowy przekrojowy (`run_portfolio`)

Kroki:
1. Dla każdego dnia zbierane są sygnały ze wszystkich spółek.
2. Sygnały są mapowane na wagi portfela `port_weight` w sposób symetryczny:

Niech:
- `n_long` = liczba spółek z sygnałem dodatnim,
- `n_short` = liczba spółek z sygnałem ujemnym.

Wagi brutto:
- jeśli występują long i short: `long_gross = 0.5·max_gross_leverage`, `short_gross = 0.5·max_gross_leverage`,
- jeśli tylko long: `long_gross = max_gross_leverage`, `short_gross = 0`,
- jeśli tylko short: `long_gross = 0`, `short_gross = max_gross_leverage`.

Podział równy:
- każda pozycja long dostaje `+ long_gross / n_long`,
- każda pozycja short dostaje `− short_gross / n_short`,
- brak sygnałów → portfel płaski.

Zwrot portfela jest sumą wkładów:
- `gross_ret_T = Σ_i ret_{i,T} · port_weight_{i,T−1}`,

koszty są liczone na obrocie wag:
- `portfolio_turnover_T = Σ_i |port_weight_{i,T} − port_weight_{i,T−1}|`,
- `cost_ret_T = portfolio_turnover_T · cost_per_turnover`,
- `net_ret_T = gross_ret_T − cost_ret_T`.

Dodatkowo raportowana jest dźwignia brutto:
- `gross_leverage_T = Σ_i |port_weight_{i,T−1}|`.

### 12.5. Narzędzie uruchomieniowe (`run_backtest.py`)

CLI wspiera:
- `--mode single` (wymaga `--symbol`),
- `--mode portfolio` (cross-sectional),
- koszty (`--commission-bps`, `--slippage-bps`),
- filtr dat (`--start-date`, `--end-date`),
- opcjonalny benchmark (`--benchmark` w CSV/Parquet z kolumnami `date`, `close`).

Jeśli podano benchmark, raportowany jest zwrot aktywny:
- `active_ret = net_ret − bm_ret`

oraz zannualizowane statystyki benchmarku i aktywne.

Wyniki zapisywane są do `data/backtests/` jako:
- `*.equity.csv` (krzywa kapitału),
- `*.daily.csv` (panel dzienny: zwroty, koszty, obrót, dźwignia, itp.).

---

## 13. Uwagi implementacyjne i ryzyka metodologiczne

1. **Modele per spółka**: zwiększa dopasowanie lokalne, ale komplikuje utrzymanie (wiele checkpointów) i może utrudniać generalizację.
2. **Przekrojowy z-score**: wyniki zależą od składu wszechświata (liczby i jakości spółek). Zmiana universe zmienia mean/std w danym dniu, a więc i progi wejścia/wyjścia.
3. **Koszty transakcyjne**: konstrukcja sygnału (rebalans, min-hold, smoothing) jest wprost „cost-aware”, ale ostateczna efektywność zależy od modelowania kosztów w backteście.
4. **Braki w danych**: `dropna` na cechach sekwencyjnych i wskaźnikach usuwa początkowy fragment historii; w praktyce wymagana jest dostatecznie długa próbka.
5. **Brak definicji pozycji i wag**: strategia generuje sygnały kierunku; alokacja (np. równe wagi, limity pozycji, gross/net exposure) jest realizowana w osobnym module backtestu.

---

## 14. Eksperymenty i wnioski

## Zakres i cel

Celem serii eksperymentów było empiryczne zbadanie zachowania strategii portfelowej w trzech reżimach rynkowych (BULL/BEAR/NORMAL) oraz ocena relatywnej przewagi względem benchmarku **buy-and-hold WIG20**. W testach koncentrowano się na: (i) partycypacji w hossie (beta/korelacja oraz stopa zwrotu vs benchmark), (ii) defensywności w bessie (obsunięcia i aktywna stopa zwrotu), (iii) wrażliwości na koszty transakcyjne i obrót, (iv) ryzyku koncentracji portfela.

## Metodyka

- **Backtest:** tryb portfelowy (cross-sectional). Dane wyjściowe: `portfolio.daily.csv` (zwroty netto, obrót, dźwignia, liczba pozycji).
- **Benchmark:** WIG20 (buy-and-hold) z dziennym zwrotem `bm_ret`. Zwrot aktywny: `active_ret = net_ret − bm_ret`.
- **Koszty:** prowizja i slippage per transakcja; w trakcie iteracji porównywano wyniki „z kosztami” oraz diagnostycznie „bez kosztów”, aby oszacować kosztową erozję sygnału.
- **Reżimy:** klasyfikacja na podstawie benchmarku (MA200 + znak nachylenia MA200):
  - **BULL (hossa):** close > MA200 i nachylenie MA200 > 0,
  - **BEAR (bessa):** close < MA200 i nachylenie MA200 < 0,
  - **NORMAL:** pozostałe dni.
- **Miary:** CAGR (ann_return), zmienność (ann_vol), max drawdown, beta/korelacja, intensywność obrotu (avg_turnover), dekompozycja brutto/koszty (ann_return_gross / ann_return_cost).

## Przebieg eksperymentów i hipotezy (co sprawdzano)

W rozmowie przeprowadzono iteracyjny cykl diagnostyki i modyfikacji strategii, kierowany obserwacjami z analizy reżimowej:

1. **Diagnoza wersji bazowej:** analiza reżimów ujawniła asymetrię działania – relatywnie lepsze zachowanie w BEAR/NORMAL i słabszą partycypację w BULL. Hipoteza: strategia ma cechy kontrariańsko‑przekrojowe i bez dodatkowego komponentu „beta” nie będzie konkurencyjna wobec buy-and-hold w długich trendach wzrostowych.
2. **Eksperyment „bull-tilt”:** dodano mechanizmy zwiększające ekspozycję w BULL (m.in. long-only) w celu poprawy bety i redukcji underperformance w hossie.
3. **Eksperyment „RegimeBlend” (wariant końcowy):** połączono trzy kierunki w jednym ustawieniu:
   - **bear-flat:** w BEAR portfel przechodzi w gotówkę (kontrola ryzyka spadkowego),
   - **BULL long-only + blend score w BULL:** mieszanie predykcji modelu z prostszym sygnałem momentum w hossie (wzmocnienie zgodności z trendem),
   - **redukcja obrotu/kosztów:** wygładzanie predykcji (EWMA), rebalans tygodniowy oraz **min-hold = 20**.

Hipoteza badawcza: (i) poprawa bety w BULL i (ii) redukcja obrotu powinny zmniejszyć lukę do buy-and-hold, a reżimowa defensywność w BEAR ograniczyć obsunięcia bez istotnej degradacji działania w pozostałych reżimach.

## Wyniki końcowe (RegimeBlend)

Poniżej zestawiono kluczowe metryki per reżim dla finalnego wariantu (z kosztami). Wartości w % dotyczą rocznych stóp zwrotu, zmienności, obsunięć oraz parametrów ekspozycji/obrotu.

| regime   |   n_days | ann_return__strategy_net   | ann_return__benchmark_bh   | ann_return__active   | ann_vol__strategy_net   | ann_vol__benchmark_bh   | max_drawdown_masked__strategy_net   | max_drawdown_masked__benchmark_bh   |   beta__strategy_net |   corr_with_benchmark__strategy_net | avg_turnover   | avg_gross_leverage   | frac_invested   |   avg_n_long | ann_return_cost__strategy_net   | ann_return_gross__strategy_net   |   sharpe_or_ir__strategy_net |
|:---------|---------:|:---------------------------|:---------------------------|:---------------------|:------------------------|:------------------------|:------------------------------------|:------------------------------------|---------------------:|------------------------------------:|:---------------|:---------------------|:----------------|-------------:|:--------------------------------|:---------------------------------|-----------------------------:|
| BEAR     |      461 | 11.26%                     | -16.98%                    | 23.64%               | 22.30%                  | 29.96%                  | -16.94%                             | -45.83%                             |                0.108 |                               0.146 | 7.14%          | 21.91%               | 21.91%          |         0.6  | -1.25%                          | 12.68%                           |                        0.505 |
| BULL     |      790 | 14.61%                     | 18.68%                     | -4.66%               | 26.52%                  | 20.17%                  | -37.72%                             | -13.18%                             |                0.685 |                               0.521 | 15.64%         | 80.51%               | 80.63%          |         2.69 | -2.72%                          | 17.83%                           |                        0.551 |
| NORMAL   |      227 | 52.47%                     | 12.97%                     | 26.22%               | 38.22%                  | 27.73%                  | -22.56%                             | -24.90%                             |                0.125 |                               0.09  | 8.27%          | 44.05%               | 44.05%          |         1.62 | -1.45%                          | 54.71%                           |                        1.373 |


## Interpretacja wyników i wnioski

### BEAR (bessa)

- **Wynik bezwzględny i względny:** CAGR strategii **11.26%** przy benchmarku **-16.98%**; zwrot aktywny **23.64%**.
- **Ekspozycja rynkowa:** beta **0.108**, korelacja **0.146**, udział rynku (**frac_invested**) **21.91%**.
- **Ryzyko:** maskowane obsunięcie strategii **-16.94%** vs benchmark **-45.83%**.
- **Wniosek akademicki:** BEAR=flat działa jak skuteczny overlay typu risk‑off: obniża ekspozycję na czynnik rynkowy i poprawia wynik względny w spadkach, co jest spójne z intuicją filtrów trendowych stosowanych do kontroli ryzyka ogonowego.

### BULL (hossa)

- **Wynik:** CAGR strategii **14.61%** vs benchmark **18.68%**; zwrot aktywny **-4.66%**.
- **Partycpacja rynkowa:** beta **0.685**, korelacja **0.521**, wysokie **frac_invested 80.63%**.
- **Rola kosztów:** wynik brutto **17.83%** i kosztowy komponent **-2.72%** przy **avg_turnover 15.64%** – koszty są czynnikiem pierwszego rzędu.
- **Ryzyko koncentracji:** średnio **2.69** pozycji długich; obsunięcie w BULL **-37.72%** vs benchmark **-13.18%**.
- **Wniosek akademicki:** RegimeBlend przywraca dodatnią ekspozycję w hossie (wysoka beta i korelacja), co zbliża wynik brutto do buy-and-hold. Ujemny active wynika przede wszystkim z kosztów transakcyjnych oraz koncentracji.

### NORMAL

- **Wynik:** CAGR strategii **52.47%** vs benchmark **12.97%**; zwrot aktywny **26.22%**.
- **Profil czynnikowy:** beta **0.125**, korelacja **0.090** – wskazuje na dominację alfa przekrojowej nad ekspozycją rynkową.
- **Ryzyko:** avg_n_long **1.62** oraz DD **-22.56%**.
- **Wniosek akademicki:** wysoki wynik w NORMAL stanowi empiryczną przesłankę efektywności selekcji przekrojowej, ale wymaga weryfikacji stabilności (okna kroczące/out-of-sample), aby ograniczyć ryzyko wnioskowania post‑hoc.

## Uogólnione wnioski (co te testy pokazują)

1. **Reżimowość jest cechą determinującą:** te same reguły alokacji generują istotnie różne profile ryzyka/zwrotu w zależności od stanu rynku. Analiza reżimowa jest więc adekwatnym narzędziem interpretacji strategii ML.
2. **Beta w hossie jest kluczową osią konstrukcyjną:** bez dodatniej bety strategia ma strukturalny problem z konkurencją wobec buy-and-hold w BULL. RegimeBlend rozwiązuje ten problem częściowo, ale kosztowość i koncentracja nadal ograniczają aktywną przewagę.
3. **Koszty transakcyjne należy modelować explicite:** obserwowalna dekompozycja brutto/koszt wskazuje, że turnover jest głównym kanałem degradacji wyniku. Stąd wynika potrzeba projektowania reguł rebalansu i utrzymania pozycji „cost-aware”.
4. **Overlay risk‑off w BEAR poprawia właściwości ogonowe:** BEAR=flat obniża obsunięcia i istotnie poprawia aktywny wynik w spadkach.
5. **Otwarte ryzyko metodologiczne:** niska liczba pozycji (koncentracja) może prowadzić do nadmiernej wrażliwości na pojedyncze spółki; wymaga to dodatkowych testów dywersyfikacji i stabilności.

## Rekomendowane dalsze testy (kontynuacja badań)

- **Top‑K + buffer rang:** selekcja K najlepszych spółek (np. 6–8) i utrzymanie pozycji, jeśli pozostaje w K+buffer. Cel: ograniczenie koncentracji oraz obsunięć.
- **Rolling / walk‑forward:** stabilność metryk w czasie (okna kroczące) i testy poza próbą.
- **Stress‑test kosztów:** siatka kosztów (np. 0/0, 2/2, 5/2, 5/5, 10/5 bps) i raport degradacji CAGR/Sharpe.
- **Ablacje komponentów:** osobne wyłączenie: smoothing, rebalance tygodniowy, min‑hold, bull‑score‑blend, bear‑flat.

## Słownik metryk

| Metryka                            | Znaczenie (interpretacja)                                                                                                                              |
|:-----------------------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------|
| regime                             | Reżim rynkowy wg benchmarku (BULL/BEAR/NORMAL). Definicja: kurs względem MA200 i znak nachylenia MA200 (aproksymacja różnicą MA w oknie slope-window). |
| ann_return                         | Roczna stopa zwrotu (geometryczna, CAGR) wyliczona z dziennych zwrotów.                                                                                |
| ann_mean_arith                     | Roczna średnia arytmetyczna zwrotów dziennych (mean * 252). Miara pomocnicza; w raportowaniu wyników preferuje się CAGR.                               |
| ann_vol                            | Roczna zmienność: odchylenie standardowe zwrotów dziennych * √252.                                                                                     |
| sharpe_invested                    | Sharpe liczony na próbie dni, w których portfel był zainwestowany (masked do dni z ekspozycją).                                                        |
| sharpe_or_ir                       | Sharpe (dla serii zwrotów) lub IR (dla zwrotów aktywnych), w tej implementacji: ann_return / ann_vol (bez stopy wolnej od ryzyka).                     |
| max_drawdown_masked                | Maksymalne obsunięcie kapitału liczone na krzywej kapitału w obrębie dni danego reżimu (maskowanie do obserwacji reżimu).                              |
| beta, corr                         | Beta i korelacja zwrotów strategii względem benchmarku; opisują ekspozycję rynkową i współzależność.                                                   |
| active_ret                         | Zwrot aktywny: net_ret − bm_ret; miara przewagi nad buy-and-hold benchmarku.                                                                           |
| ann_return_gross / ann_return_cost | Dekompozycja wyniku: część „brutto” (przed kosztami) oraz wkład kosztów (prowizje+slippage).                                                           |
| avg_turnover                       | Średni dzienny obrót portfela; proxy intensywności handlu i główne źródło kosztów transakcyjnych.                                                      |
| avg_gross_leverage / frac_invested | Średnia ekspozycja brutto i udział czasu/kapitału w rynku; opisują jak często i jak silnie portfel jest zainwestowany.                                 |
| avg_n_long / avg_n_short           | Średnia liczba pozycji długich/krótkich; proxy dywersyfikacji oraz ryzyka idiosynkratycznego.                                                          |
| hit_rate                           | Udział dni z dodatnim zwrotem (dla serii: strategia, benchmark lub zwrot aktywny).                                                                     |