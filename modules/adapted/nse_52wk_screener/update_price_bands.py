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


"""
Nightly per-symbol price-band feed via Angel One SmartAPI.

Angel's full quote returns each stock's upper/lower circuit limits, from which we
derive the daily price band % (2 / 5 / 10 / 20). We fetch bands for the NON-F&O
universe (F&O stocks have no band) and write data/price_bands.csv, which the
screener reads for the "Upper circuit = 20%" filter.

Runs unattended in GitHub Actions — SmartAPI supports programmatic login via a
TOTP secret, so no manual step. Requires these env vars (GitHub secrets):
    ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET

    python update_price_bands.py

NOTE: needs valid Angel creds to run — untested until the secrets are added.
"""

import contextlib
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import requests

IST = ZoneInfo("Asia/Kolkata")
UNIVERSE_PATH = "data/nse_equity_list.csv"
FO_PATH = "data/fo_stocks.csv"
OUT_PATH = "data/price_bands.csv"
SCRIP_MASTER = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"

STANDARD_BANDS = [2, 5, 10, 20]
FULL_BATCH = 50  # SmartAPI FULL-quote token limit per request
SLEEP_BETWEEN = 1.0  # be polite to the rate limiter
MIN_SUCCESS_FRAC = 0.5  # abort (keep yesterday's file) if we get less than this


def _env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        print(f"ERROR: missing env var {name}", file=sys.stderr)
        sys.exit(2)
    return v


def login():
    import pyotp
    from SmartApi import SmartConnect

    api_key = _env("ANGEL_API_KEY")
    client = _env("ANGEL_CLIENT_CODE")
    pin = _env("ANGEL_PIN")
    totp_secret = _env("ANGEL_TOTP_SECRET")
    obj = SmartConnect(api_key=api_key)
    totp = pyotp.TOTP(totp_secret).now()
    sess = obj.generateSession(client, pin, totp)
    if not sess or not sess.get("status"):
        print(f"ERROR: Angel login failed: {sess}", file=sys.stderr)
        sys.exit(3)
    return obj


def non_fno_symbols() -> set[str]:
    uni = pd.read_csv(UNIVERSE_PATH)
    uni.columns = [c.strip() for c in uni.columns]
    syms = set(uni["SYMBOL"].astype(str).str.strip().str.upper())
    try:
        fo = pd.read_csv(FO_PATH)
        fno = set(fo[fo.columns[0]].astype(str).str.strip().str.upper())
    except Exception:
        fno = set()
    return syms - fno


def token_map(target: set[str]) -> dict[str, str]:
    """Map NSE equity Symbol -> Angel symbolToken from the public scrip master."""
    r = requests.get(SCRIP_MASTER, timeout=60)
    r.raise_for_status()
    out: dict[str, str] = {}
    for row in r.json():
        if row.get("exch_seg") != "NSE":
            continue
        sym = str(row.get("symbol", ""))
        if not sym.endswith("-EQ"):
            continue
        name = str(row.get("name", "")).strip().upper()
        if name in target and name not in out:
            out[name] = str(row.get("token"))
    return out


def _band_from(upper, close):
    try:
        upper, close = float(upper), float(close)
    except (TypeError, ValueError):
        return None
    if close <= 0 or upper <= close:
        return None
    raw = (upper - close) / close * 100.0
    nearest = min(STANDARD_BANDS, key=lambda b: abs(b - raw))
    return nearest if abs(nearest - raw) <= 1.0 else round(raw)


def fetch_bands(obj, sym_token: dict[str, str]) -> dict[str, int]:
    tok_sym = {v: k for k, v in sym_token.items()}
    tokens = list(sym_token.values())
    bands: dict[str, int] = {}
    for i in range(0, len(tokens), FULL_BATCH):
        chunk = tokens[i : i + FULL_BATCH]
        try:
            resp = obj.getMarketData(mode="FULL", exchangeTokens={"NSE": chunk})
            fetched = (resp or {}).get("data", {}).get("fetched", []) or []
        except Exception as e:
            print(f"  batch {i}: error {e}", file=sys.stderr)
            fetched = []
        for row in fetched:
            tok = str(row.get("symbolToken"))
            band = _band_from(row.get("upperCircuit"), row.get("close"))
            if band is not None and tok in tok_sym:
                bands[tok_sym[tok]] = band
        time.sleep(SLEEP_BETWEEN)
    return bands


def main():
    target = non_fno_symbols()
    print(f"{len(target)} non-F&O symbols to price")
    obj = login()
    sym_token = token_map(target)
    print(f"mapped {len(sym_token)} symbols to Angel tokens")
    if not sym_token:
        print("ERROR: no tokens mapped; aborting without overwrite", file=sys.stderr)
        sys.exit(4)

    bands = fetch_bands(obj, sym_token)
    frac = len(bands) / max(1, len(sym_token))
    print(f"got bands for {len(bands)}/{len(sym_token)} ({frac:.0%})")
    if frac < MIN_SUCCESS_FRAC:
        print("ERROR: too few bands; keeping yesterday's file", file=sys.stderr)
        sys.exit(5)

    as_of = datetime.now(IST).strftime("%Y-%m-%d")
    out = pd.DataFrame([{"Symbol": s, "Band": b, "AsOf": as_of} for s, b in sorted(bands.items())])
    out.to_csv(OUT_PATH, index=False)
    n20 = int((out["Band"] == 20).sum())
    print(f"Wrote {len(out)} bands to {OUT_PATH} (as of {as_of}); {n20} at 20%")

    with contextlib.suppress(Exception):
        obj.terminateSession(_env("ANGEL_CLIENT_CODE"))


if __name__ == "__main__":
    main()
