"""Saxo Bank OAuth2 (PKCE) helper — login, refresh, and token storage."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, cast

import httpx
from dotenv import load_dotenv

load_dotenv()

AUTH_BASE = (os.getenv("SAXO_AUTH_BASE") or "https://sim.logonvalidation.net").rstrip("/")
OPENAPI_BASE = (
    os.getenv("SAXO_OPENAPI_BASE") or "https://gateway.saxobank.com/sim/openapi"
).rstrip("/")
APP_KEY = (os.getenv("SAXO_APP_KEY") or "").strip()
APP_URL = (os.getenv("SAXO_APP_URL") or "").strip().rstrip("/")
APP_SECRET = os.getenv("SAXO_APP_SECRET")  # optional

TOKENS_PATH = Path(".secrets/saxo_tokens.json")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def make_code_verifier() -> str:
    # 32 bytes => 43 char base64url string (RFC 7636 recommendation)
    return _b64url(secrets.token_bytes(32))


def make_code_challenge(verifier: str) -> str:
    """Generate a code challenge for PKCE from the given verifier."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return _b64url(digest)


@dataclass
class Tokens:
    access_token: str
    access_exp: float  # epoch seconds
    refresh_token: Optional[str]
    refresh_exp: Optional[float]
    code_verifier: str

    @staticmethod
    def from_token_response(resp: dict[str, Any], code_verifier: str) -> "Tokens":
        now = time.time()
        return Tokens(
            access_token=resp["access_token"],
            access_exp=now + float(resp.get("expires_in", 1200)) - 30,  # 30s early
            refresh_token=resp.get("refresh_token"),
            refresh_exp=(now + float(resp.get("refresh_token_expires_in", 0)) - 30)
            if resp.get("refresh_token_expires_in")
            else None,
            code_verifier=code_verifier,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "access_exp": self.access_exp,
            "refresh_token": self.refresh_token,
            "refresh_exp": self.refresh_exp,
            "code_verifier": self.code_verifier,
        }

    @staticmethod
    def from_json(d: dict[str, Any]) -> "Tokens":
        refresh_raw = d.get("refresh_exp")
        if isinstance(refresh_raw, (int, float, str)):
            refresh_exp: Optional[float] = float(refresh_raw)
        else:
            refresh_exp = None

        return Tokens(
            access_token=d["access_token"],
            access_exp=float(d["access_exp"]),
            refresh_token=d.get("refresh_token"),
            refresh_exp=refresh_exp,
            code_verifier=d["code_verifier"],
        )


class TokenStore:
    def __init__(self, path: Path = TOKENS_PATH) -> None:
        self.path = path

    def save(self, tokens: Tokens) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tokens.to_json(), indent=2))

    def load(self) -> Optional[Tokens]:
        if not self.path.exists():
            return None
        return Tokens.from_json(json.loads(self.path.read_text()))

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


class SaxoPKCE:
    def __init__(self, app_key: str, app_url: str, auth_base: str) -> None:
        self.app_key = app_key
        self.app_url = app_url
        self.auth_base = auth_base

    def _authorize_url(self, redirect_uri: str, state: str, code_challenge: str) -> str:
        q = {
            "response_type": "code",
            "client_id": self.app_key,
            "state": state,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{self.auth_base}/authorize?{urllib.parse.urlencode(q)}"

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str) -> dict[str, Any]:
        """Exchange authorization code for tokens.
        Two variants: (A) confidential app (Basic Auth) or (B) pure PKCE (no secret)
        """
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        use_client_secret = bool(APP_SECRET)
        # auth = (self.app_key, APP_SECRET) if use_client_secret else None
        if use_client_secret:
            secret: str = cast(str, APP_SECRET)
            auth: tuple[str, str] = (self.app_key, secret)
            form["client_id"] = self.app_key
        else:
            auth = ("", "")
            form["client_id"] = self.app_key
            form["code_verifier"] = code_verifier

        with httpx.Client(timeout=30) as c:
            r = c.post(f"{self.auth_base}/token", data=form, headers=headers, auth=auth)
            if not r.is_success:
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                raise SystemExit(
                    "Token exchange failed.\n"
                    f"  status   : {r.status_code}\n"
                    f"  url      : {r.request.url}\n"
                    f"  ctype    : {r.headers.get('content-type', '')}\n"
                    f"  response : {body!r}\n"
                )
            return r.json()  # type: ignore[return-value]

    def refresh(self, refresh_token: str, code_verifier: str) -> dict[str, Any]:
        """Refresh tokens using the refresh token."""
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "code_verifier": code_verifier,
            "redirect_uri": self.app_url,  # Some providers strictly require this even on refresh
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        use_client_secret = bool(APP_SECRET)
        if use_client_secret:
            secret: str = cast(str, APP_SECRET)
            auth: tuple[str, str] = (self.app_key, secret)
            # Some implementations might want client_id in body too, but Basic Auth is standard
            # for confidential clients. We'll add it to body just in case it's not in Auth header
            # or if the server expects it there for consistency.
            data["client_id"] = self.app_key
        else:
            auth = ("", "")
            data["client_id"] = self.app_key

        with httpx.Client(timeout=30) as c:
            r = c.post(f"{self.auth_base}/token", data=data, headers=headers, auth=auth)
            if not r.is_success:
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                raise SystemExit(f"Token refresh failed ({r.status_code}). Details: {body!r}")
            return r.json()  # type: ignore[return-value]


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Catch the OAuth redirect with code."""

    expected_state: str = ""
    expected_path: str = "/oauth/callback"
    result: dict[str, str] | None = None
    done: threading.Event = threading.Event()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != _CallbackHandler.expected_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not the OAuth callback path.")
            return

        qs = urllib.parse.parse_qs(parsed.query)
        code_vals = qs.get("code")
        state_vals = qs.get("state")
        code: Optional[str] = code_vals[0] if code_vals else None
        state: Optional[str] = state_vals[0] if state_vals else None
        if code and state and state == _CallbackHandler.expected_state:
            _CallbackHandler.result = {"code": code, "state": state}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK. You can close this tab.")
            _CallbackHandler.done.set()
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid or missing OAuth parameters.")

    def log_message(self, fmt: str, *args: Any) -> None:  # silence default logging
        return


def login(port: int = 8765) -> Tokens:
    """Perform OAuth2 PKCE login flow and return Tokens."""
    if not APP_KEY or not APP_URL:
        raise SystemExit("SAXO_APP_KEY and SAXO_APP_URL must be set in .env file.")

    app_url = urllib.parse.urlparse(APP_URL)
    if not app_url.path:
        raise SystemExit(
            "SAXO_APP_URL must include a path (e.g., http://localhost/oauth/callback)."
        )
    if port in (80, 443):
        scheme = "https" if port == 443 else "http"
        redirect_uri = f"{scheme}://localhost{app_url.path}"
    else:
        redirect_uri = f"http://localhost:{port}{app_url.path}"

    pkce = SaxoPKCE(APP_KEY, APP_URL, AUTH_BASE)
    code_verifier = make_code_verifier()
    code_challenge = make_code_challenge(code_verifier)

    state = secrets.token_urlsafe(24)

    _CallbackHandler.expected_state = state
    _CallbackHandler.expected_path = app_url.path
    _CallbackHandler.result = None
    _CallbackHandler.done.clear()

    try:
        server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    except OSError as e:
        raise SystemExit(f"Cannot bind to 127.0.0.1:{port} ({e}). Try a different --port.") from e

    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()

    try:
        url = pkce._authorize_url(redirect_uri, state, code_challenge)
        print(f"[auth] Opening browser for login...\n{url}\n")  # noqa: T201

        try:
            webbrowser.open(url, new=1, autoraise=True)
        except webbrowser.Error as e:
            raise SystemExit(f"Failed to open browser: {e}") from e

        if not _CallbackHandler.done.wait(120):
            raise TimeoutError("No OAuth callback received. Did you approve in the browser?")

        if not _CallbackHandler.result:
            raise RuntimeError("No authorization code in callback.")

        code = _CallbackHandler.result["code"]
        token_resp = pkce.exchange_code(code, redirect_uri, code_verifier)
        tokens = Tokens.from_token_response(token_resp, code_verifier)
        TokenStore().save(tokens)
        print("[auth] Tokens saved to .secrets/saxo_tokens.json")  # noqa: T201
        return tokens
    finally:
        server.shutdown()


def ensure_access_token() -> str:
    """Return a valid access token, refreshing if needed (tokens must exist)."""
    store = TokenStore()
    tokens = store.load()
    if not tokens:
        raise SystemExit("No tokens yet. Run: python data/scripts/saxo_auth.py login")

    now = time.time()
    if now < tokens.access_exp:
        return tokens.access_token

    if tokens.refresh_token and (tokens.refresh_exp is None or now < tokens.refresh_exp):
        pkce = SaxoPKCE(APP_KEY or "", APP_URL or "", AUTH_BASE)
        resp = pkce.refresh(tokens.refresh_token, tokens.code_verifier)
        new_tokens = Tokens.from_token_response(resp, tokens.code_verifier)
        store.save(new_tokens)
        print("[auth] Access token refreshed.")  # noqa: T201
        return new_tokens.access_token

    raise SystemExit("Refresh token expired or missing. Please login again.")


def print_status() -> None:
    """Print the content and expiry status of the stored tokens."""
    store = TokenStore()
    tokens = store.load()
    if not tokens:
        print("[status] No tokens found.")  # noqa: T201
        return

    now = time.time()

    # Access Token
    acc_rem = tokens.access_exp - now
    if acc_rem > 0:
        acc_status = f"VALID (expires in {int(acc_rem // 60)}m {int(acc_rem % 60)}s)"
    else:
        acc_status = f"EXPIRED ({int(abs(acc_rem) // 60)}m {int(abs(acc_rem) % 60)}s ago)"

    # Refresh Token
    if tokens.refresh_token:
        if tokens.refresh_exp:
            ref_rem = tokens.refresh_exp - now
            if ref_rem > 0:
                ref_status = f"VALID (expires in {ref_rem / 3600:.1f} hours)"
            else:
                ref_status = "EXPIRED"
        else:
            ref_status = "VALID (no expiry set)"
    else:
        ref_status = "NONE"

    print("--- Saxo Token Status ---")  # noqa: T201
    print(f"Access Token  : {acc_status}")  # noqa: T201
    print(f"Refresh Token : {ref_status}")  # noqa: T201
    print(f"Token Path    : {store.path.absolute()}")  # noqa: T201


def force_refresh() -> None:
    """Explicitly refresh the access token now."""
    store = TokenStore()
    tokens = store.load()
    if not tokens or not tokens.refresh_token:
        print("[refresh] No refresh token available. Please login first.")  # noqa: T201
        return

    # We purposefully don't check expiration, just try to refresh
    pkce = SaxoPKCE(APP_KEY or "", APP_URL or "", AUTH_BASE)
    try:
        resp = pkce.refresh(tokens.refresh_token, tokens.code_verifier)
        new_tokens = Tokens.from_token_response(resp, tokens.code_verifier)
        store.save(new_tokens)
        print("[refresh] SUCCESS. New access token obtained.")  # noqa: T201
        print_status()
    except Exception as e:
        print(f"[refresh] FAILED: {e}")  # noqa: T201


def logout() -> None:
    """Clear saved tokens."""
    TokenStore().clear()
    print("[auth] Tokens cleared.")  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser(description="Saxo OpenAPI OAuth2 (PKCE) helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="Interactive login (opens browser)")
    p_login.add_argument(
        "--port", type=int, default=8765, help="Local callback port (matches APP_URL path)"
    )
    p_login.set_defaults(func=lambda a: login(a.port))

    sub.add_parser(
        "ensure", help="Prints a valid access token (refreshes if needed)"
    ).set_defaults(
        func=lambda a: print(ensure_access_token())  # noqa: T201
    )
    sub.add_parser("status", help="Show token status and expiry").set_defaults(
        func=lambda a: print_status()
    )
    sub.add_parser("refresh", help="Force a token refresh").set_defaults(
        func=lambda a: force_refresh()
    )
    sub.add_parser("logout", help="Delete stored tokens").set_defaults(func=lambda a: logout())

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
