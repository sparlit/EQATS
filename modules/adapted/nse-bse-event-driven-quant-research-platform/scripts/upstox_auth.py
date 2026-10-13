from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""Upstox authentication utilities - replicates the BseIndiaApi pattern
(streamlit_upstox_auth_naru.py + token_utils.py + refresh_upstox_token.py)
as a plain CLI.

Subcommands:
    url      print the browser login dialog URL
    login    print URL, accept pasted redirect URL or bare code, exchange,
             write upstox_tokens.json (same format as BseIndiaApi)
    refresh  rotate tokens via grant_type=refresh_token (token_utils logic)
    auto     get_valid_access_token(): use cached token, else refresh, else exit
    whoami   GET /v2/user/profile with the current token

Credentials come from .env (never hardcoded here):
    UPSTOX_API_KEY, UPSTOX_API_SECRET, UPSTOX_REDIRECT_URI
"""


import argparse
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TOKEN_FILE = ROOT / "upstox_tokens.json"
ENV_FILE = ROOT / ".env"

LOGIN_DIALOG_URL = "https://api.upstox.com/v2/login/authorization/dialog"
TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
PROFILE_URL = "https://api.upstox.com/v2/user/profile"


def redirect_fallbacks() -> list[tuple[str, str]]:
    """Optional secondary app credentials from .env - never hardcoded here."""
    env = load_dotenv()
    pairs: list[tuple[str, str]] = []
    fb_key = env.get("UPSTOX_FALLBACK_API_KEY", "")
    fb_redirect = env.get("UPSTOX_FALLBACK_REDIRECT_URI", "")
    if fb_key and fb_redirect:
        pairs.append((fb_key, fb_redirect))
    return pairs


def load_dotenv(path: Path = ENV_FILE) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip("'\"")
    return env


def get_creds(overrides: dict[str, str] | None = None) -> tuple[str, str, str]:
    merged = {**load_dotenv(), **os.environ}
    if overrides:
        merged.update(overrides)
    api_key = merged.get("UPSTOX_API_KEY", "")
    api_secret = merged.get("UPSTOX_API_SECRET", "")
    redirect_uri = merged.get("UPSTOX_REDIRECT_URI", "")
    if not (api_key and api_secret and redirect_uri):
        raise SystemExit(
            "missing UPSTOX_API_KEY / UPSTOX_API_SECRET / UPSTOX_REDIRECT_URI "
            f"in {ENV_FILE} or environment"
        )
    return api_key, api_secret, redirect_uri


def build_login_url(api_key: str, redirect_uri: str) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": api_key,
            "redirect_uri": redirect_uri,
        }
    )
    return f"{LOGIN_DIALOG_URL}?{query}"


def extract_code(pasted: str) -> str:
    pasted = pasted.strip()
    match = re.search(r"[?&]code=([^&\s]+)", pasted)
    if match:
        return match.group(1)
    if re.fullmatch(r"[\w\-]{10,}", pasted):
        return pasted
    raise SystemExit(f"could not find an authorization code in: {pasted[:80]}...")


def save_token_file(payload: dict[str, object]) -> None:
    """Same file/format as BseIndiaApi's upstox_tokens.json."""
    TOKEN_FILE.write_text(json.dumps(payload, indent=4))
    _set_env_vars({"UPSTOX_ACCESS_TOKEN": str(payload.get("access_token", ""))})


def load_token_file() -> dict[str, object]:
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(f"{TOKEN_FILE} not found - run `login` first")
    return json.loads(TOKEN_FILE.read_text())


def _set_env_vars(updates: dict[str, str]) -> None:
    lines: list[str] = []
    existing: dict[str, int] = {}
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text().splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"\s*(UPSTOX_[A-Z_]+)\s*=", line)
            if m:
                existing[m.group(1)] = i
    for key, value in updates.items():
        rendered = f"{key}={value}"
        if key in existing:
            lines[existing[key]] = rendered
        else:
            lines.append(rendered)
            existing[key] = len(lines) - 1
    ENV_FILE.write_text("\n".join(lines) + "\n")


def exchange_code(
    code: str,
    *,
    api_key: str,
    api_secret: str,
    redirect_uri: str,
    http_client: httpx.Client | None = None,
) -> dict[str, object]:
    own = http_client or httpx.Client(timeout=30.0)
    resp = own.post(
        TOKEN_URL,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "code": code,
            "client_id": api_key,
            "client_secret": api_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    if resp.status_code != 200:
        raise SystemExit(f"token exchange failed ({resp.status_code}): {resp.text[:300]}")
    payload: dict[str, object] = resp.json()
    save_token_file(payload)
    return payload


def refresh_tokens(
    *,
    api_key: str,
    api_secret: str,
    http_client: httpx.Client | None = None,
) -> dict[str, object]:
    """token_utils.get_valid_access_token() rotation path."""
    data = load_token_file()
    refresh_token = str(data.get("refresh_token") or data.get("extended_token") or "")
    if not refresh_token:
        raise SystemExit("no refresh_token in upstox_tokens.json - run `login`")
    own = http_client or httpx.Client(timeout=30.0)
    resp = own.post(
        TOKEN_URL,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_id": api_key,
            "client_secret": api_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "redirect_uri": os.environ.get("UPSTOX_REDIRECT_URI", "https://api.upstox.com"),
        },
    )
    if resp.status_code != 200:
        raise SystemExit(f"refresh failed ({resp.status_code}): {resp.text[:300]}")
    payload: dict[str, object] = resp.json()
    merged = {**data, **payload}
    save_token_file(merged)
    return merged


def get_valid_access_token() -> str:
    """Mirror of token_utils.get_valid_access_token()."""
    try:
        data = load_token_file()
    except FileNotFoundError as exc:
        raise SystemExit(str(exc)) from None
    token = str(data.get("access_token") or "")
    if token:
        return token
    if data.get("refresh_token") or data.get("extended_token"):
        api_key, api_secret, _ = get_creds()
        refreshed = refresh_tokens(api_key=api_key, api_secret=api_secret)
        return str(refreshed["access_token"])
    raise SystemExit("no usable tokens - run `login`")


def whoami(token: str, http_client: httpx.Client | None = None) -> dict[str, object]:
    own = http_client or httpx.Client(timeout=30.0)
    resp = own.get(
        PROFILE_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    if resp.status_code != 200:
        raise SystemExit(f"profile probe failed ({resp.status_code}): {resp.text[:300]}")
    profile: dict[str, object] = resp.json()
    return profile


def masked(payload: dict[str, object]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in payload.items():
        if isinstance(value, str) and ("token" in key.lower()) and len(value) > 12:
            out[key] = value[:8] + "...<redacted>"
        else:
            out[key] = value
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Upstox authentication CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("url", help="print the login dialog URL")
    sub.add_parser("login", help="interactive: paste redirected URL/code")
    sub.add_parser("refresh", help="rotate via refresh_token")
    sub.add_parser("auto", help="get_valid_access_token()")
    sub.add_parser("whoami", help="verify token via /v2/user/profile")
    args = parser.parse_args(argv)

    if args.command == "url":
        api_key, _, redirect_uri = get_creds()
        print(build_login_url(api_key, redirect_uri))
        return 0

    if args.command == "login":
        api_key, api_secret, redirect_uri = get_creds()
        print("1. open this URL in a browser and log in:\n")
        print("   " + build_login_url(api_key, redirect_uri) + "\n")
        pasted = input("2. paste the redirected URL (or bare code): ")
        code = extract_code(pasted)
        payload = exchange_code(
            code, api_key=api_key, api_secret=api_secret, redirect_uri=redirect_uri
        )
        print("3. saved upstox_tokens.json:")
        print(json.dumps(masked(payload), indent=2))
        return 0

    if args.command == "refresh":
        api_key, api_secret, _ = get_creds()
        payload = refresh_tokens(api_key=api_key, api_secret=api_secret)
        print(json.dumps(masked(payload), indent=2))
        return 0

    if args.command == "auto":
        print(get_valid_access_token())
        return 0

    if args.command == "whoami":
        profile = whoami(get_valid_access_token())
        if "data" in profile and isinstance(profile["data"], dict):
            profile = profile["data"]
        interesting = {
            k: profile.get(k)
            for k in ("user_id", "user_name", "email", "exchanges", "broker")
            if k in profile
        }
        print(json.dumps(interesting, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
