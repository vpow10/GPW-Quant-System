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