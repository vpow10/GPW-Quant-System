# Scripts Cheatsheet

### Quick start (TL;DR)
1. Install deps
```bash
pip install -r requirements.txt
```
2. Create `.env` file based on `.env.example`, filling in your Saxo app credentials.
3. Login to Saxo and get tokens:
```bash
python saxo_auth.py login
```
4. Probe the API:
- Instruments:
```bash
python saxo_probe.py instruments --keywords PKN --asset-type Stock --top 5
```
- Charts:
```bash
python saxo_probe.py chart --uic 21 --asset-type FxSpot --horizon 60 --count 120
```

### .env.example
| Var                 | Used by         | Required? | Default in code                            | What it should look like                                               |
| ------------------- | --------------- | --------: | ------------------------------------------ | ---------------------------------------------------------------------- |
| `SAXO_AUTH_BASE`    | `saxo_auth.py`  |        No | `https://sim.logonvalidation.net`          | Auth server base (no trailing slash needed)                            |
| `SAXO_OPENAPI_BASE` | `saxo_auth.py`  |        No | `https://gateway.saxobank.com/sim/openapi` | OpenAPI base (no trailing slash needed)                                |
| `SAXO_OPENAPI_BASE` | `saxo_probe.py` |   **Yes** | *(none; must be set!)*                     | Same as above; **must** exist for `saxo_probe.py`                      |
| `SAXO_APP_KEY`      | `saxo_auth.py`  |   **Yes** | *(empty)*                                  | Your app key / client ID                                               |
| `SAXO_APP_URL`      | `saxo_auth.py`  |   **Yes** | *(empty)*                                  | Must include a **path**, e.g. `http://localhost/oauth/callback`        |
| `SAXO_APP_SECRET`   | `saxo_auth.py`  |  Optional | *(unset)*                                  | If set, uses confidential flow (Basic Auth); otherwise PKCE only       |
| `SAXO_TOKEN`        | `saxo_probe.py` |        No | *(unused)*                                 | **Not used** by current code (leftover helper exists but isn’t called) |


### saxo_auth.py
Handles Saxo Bank OAuth2 using PKCE (and optionally client secret). It opens your browser to log in, catches the redirect on localhost, exchanges the code for tokens, refreshes them when needed, and stores everything in .secrets/saxo_tokens.json.

#### Usage
```bash
python saxo_auth.py <command> [options]
```
#### Commands and args
| Command  | Args     | Type / Default        | What it does                                                                                                                                                                                          |
| -------- | -------- | --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `login`  | `--port` | `int`, default `8765` | Starts a tiny HTTP server on `127.0.0.1:<port>`, opens the browser to Saxo’s `/authorize`, receives `code` on `APP_URL` path, exchanges it for tokens, and saves them to `.secrets/saxo_tokens.json`. |
| `ensure` | *(none)* | –                     | Prints a **valid access token** to stdout. If the saved access token is expired and the refresh token is still valid, it **refreshes** and updates the file.                                          |
| `logout` | *(none)* | –                     | Deletes `.secrets/saxo_tokens.json`.                                                                                                                                                                  |
### saxo_probe.py
Tiny CLI client that calls two OpenAPI endpoints:
- /ref/v1/instruments to search instruments,
- /chart/v3/charts to pull recent OHLC bars (candles).
saxo_probe.py depends on saxo_auth.py for a valid access token (so you must run saxo_auth.py login once before probing).

#### Usage
```bash
python saxo_probe.py <command> [options]
```
#### Commands and args

##### instruments
```bash
python saxo_probe.py instruments --keywords <text> --asset-type <type> --top <n>
```
| Arg            | Type / Default         | Meaning                 | Values / notes                                                                              |
| -------------- | ---------------------- | ----------------------- | ------------------------------------------------------------------------------------------- |
| `--keywords`   | `str`, default `PKN`   | Free-text search        | e.g., `PKN`, `EURUSD`, `APPLE`                                                              |
| `--asset-type` | `str`, default `Stock` | Saxo asset class filter | e.g., `Stock`, `FxSpot`, `CFD`, etc. (**Script doesn’t validate**; must be valid for Saxo.) |
| `--top`        | `int`, default `5`     | Max number of results   | Positive integer                                                                            |
Output: prints a count, then lines like
- UIC=25275 | PKN | Stock | POLSKI KONCERN NAFTOWY ORLEN…

##### charts
```bash
python saxo_probe.py chart --uic <id> --asset-type <type> --horizon <mins> --count <n>
```
| Arg            | Type / Default         | Meaning                 | Values / notes                                                                |
| -------------- | ---------------------- | ----------------------- | ----------------------------------------------------------------------------- |
| `--uic`        | `int`, **required**    | Instrument ID (UIC)     | Use a UIC from `instruments` or that you already know                         |
| `--asset-type` | `str`, default `Stock` | Asset class             | e.g., `Stock`, `FxSpot`, etc. (no local validation)                           |
| `--horizon`    | `int`, default `1440`  | Bar size in **minutes** | `1, 5, 10, 15, 30, 60, 240, 1440, …` (Saxo-supported intervals; 1440 = daily) |
| `--count`      | `int`, default `100`   | Max number of samples   | Up to **1200**

Output: prints lines like
```bash
EURUSD | horizon=60 | samples=120
2024-01-01T10:00:00Z  O:... H:... L:... C:... V:...
...
```


### `saxo_basic.py` — Place or preview orders

Handles basic order creation via Saxo OpenAPI (`/trade/v2/orders` and `/trade/v2/orders/preview`).  
Requires a valid access token (from `saxo_auth.py login`) and your `SAXO_ACCOUNT_KEY` set in `.env`.

#### Env vars
| Var | Required? | Default | Description |
|-----|:----------:|---------|--------------|
| `SAXO_ACCOUNT_KEY` | **Yes** | – | Your trading account key (needed to send orders) |
| `SAXO_OPENAPI_BASE` | **Yes** | `https://gateway.saxobank.com/sim/openapi` | API base URL |
| `SAXO_CLIENT_TIMEOUT` | No | `30` | HTTP timeout (seconds) |
| `JOURNAL_DIR` | No | `journals` | Directory for JSONL trade logs |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG`, `INFO`, etc.) |

---

#### Usage
```bash
python saxo_basic.py [options]
```

| Arg | Type / Default | Required | Meaning |
|-----|----------------|:--------:|---------|
| `--uic` | `int` | **Yes** | Instrument UIC |
| `--asset-type` | `str`, `Stock` | No | Saxo asset class (e.g. `Stock`, `FxSpot`) |
| `--side` | `Buy` \| `Sell` | **Yes** | Order side |
| `--amount` | `float`, `1.0` | No | Quantity / nominal |
| `--order-type` | `Market` \| `Limit` | No | Order type |
| `--price` | `float` | If Limit | Required for limit orders |
| `--place` | flag | No | Actually places the order (otherwise preview only) |
| `--tag` | `str` | No | Optional label saved in log |

---

#### Examples

**Preview only (no execution)**  
Runs `/trade/v2/orders/preview` to simulate an order:
```bash
python saxo_basic.py \
  --uic 21 \
  --asset-type FxSpot \
  --side Buy \
  --amount 10000 \
  --order-type Market \
  --tag "dry-run"
```

**Market order (execute trade)**
```bash
python saxo_basic.py \
  --uic 21 \
  --asset-type FxSpot \
  --side Sell \
  --amount 10000 \
  --order-type Market \
  --place \
  --tag "market-run"
```

**Limit order (uses all flags)**
```bash
python saxo_basic.py \
  --uic 25275 \
  --asset-type Stock \
  --side Buy \
  --amount 5 \
  --order-type Limit \
  --price 62.50 \
  --place \
  --tag "cheatsheet-demo"
```

---

#### Output & logs
- Prints a short confirmation and top-level response fields.  
- Writes a JSON record to `journals/orders.jsonl` containing:
  - Timestamp (`ts`)
  - Mode (`PREVIEW` or `PLACE`)
  - Payload and API response
  - Optional `tag`

Example log entry:
```json
{
  "ts": "2025-11-02T10:33:41Z",
  "mode": "PLACE",
  "uic": 21,
  "side": "Buy",
  "amount": 10000,
  "order_type": "Market",
  "response": {...},
  "tag": "market-run"
}
```

> 💡 **Tip:** Run with `LOG_LEVEL=DEBUG` to see full request and response details.
