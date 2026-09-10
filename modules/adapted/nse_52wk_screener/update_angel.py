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
Same-day daily append via Angel One SmartAPI (authoritative NSE EOD).

Yahoo's NSE end-of-day bar lags ~a day, so the Yahoo-based nightly job left the
screener stale until the next day. Angel (a broker with direct exchange data) has
today's close/high the moment the market closes, so this job — run right after
close — pushes TODAY's high onto each stock's frontier and refreshes LastClose /
LastDate. The screener is then fresh the same evening.

Scope: price + high + frontier only. AvgVol20d (a 20-day average, barely moves
day to day) and split re-adjustment are handled by the weekly Yahoo reconciliation
(update_history.py). Reuses the Angel auth already used by the band feed.

Env (GitHub secrets): ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET

    python update_angel.py
"""
import contextlib
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import frontier as F
import nse_screener as s
import pandas as pd
import requests

IST = ZoneInfo("Asia/Kolkata")
SCRIP_MASTER = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
FULL_BATCH = 50
SLEEP_BETWEEN = 1.0
MIN_SUCCESS_FRAC = 0.5
# Guard against split/anomaly days: if today's price vs stored last close is
# outside this ratio, skip the frontier push (the weekly Yahoo job re-backfills).
RATIO_LO, RATIO_HI = 0.6, 1.7


def _env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        print(f"ERROR: missing env var {name}", file=sys.stderr)
        sys.exit(2)
    return v


def login():
    import pyotp
    from SmartApi import SmartConnect

    obj = SmartConnect(api_key=_env("ANGEL_API_KEY"))
    totp = pyotp.TOTP(_env("ANGEL_TOTP_SECRET")).now()
    sess = obj.generateSession(_env("ANGEL_CLIENT_CODE"), _env("ANGEL_PIN"), totp)
    if not sess or not sess.get("status"):
        print(f"ERROR: Angel login failed: {sess}", file=sys.stderr)
        sys.exit(3)
    return obj


def token_map(target: set[str]) -> dict[str, str]:
    r = requests.get(SCRIP_MASTER, timeout=60)
    r.raise_for_status()
    out: dict[str, str] = {}
    for row in r.json():
        if row.get("exch_seg") != "NSE":
            continue
        sym = str(row.get("symbol", ""))
        if not (sym.endswith(("-EQ", "-BE"))):  # both NSE cash series
            continue
        name = str(row.get("name", "")).strip().upper()
        if name in target and name not in out:
            out[name] = str(row.get("token"))
    return out


def _trade_date(row, fallback: str) -> str:
    """ISO trade date from the quote (exchTradeTime), so a holiday run doesn't
    mis-stamp the previous session's data as today."""
    for key in ("exchTradeTime", "exchFeedTime"):
        v = row.get(key)
        if v:
            d = pd.to_datetime(v, errors="coerce")
            if pd.notna(d):
                return d.date().isoformat()
    return fallback


def fetch_quotes(obj, sym_token: dict[str, str], fallback_date: str) -> dict[str, tuple[float, float, str]]:
    """symbol -> (high, close, trade_date) from Angel FULL quotes."""
    tok_sym = {v: k for k, v in sym_token.items()}
    tokens = list(sym_token.values())
    out: dict[str, tuple[float, float, str]] = {}
    for i in range(0, len(tokens), FULL_BATCH):
        chunk = tokens[i : i + FULL_BATCH]
        try:
            resp = obj.getMarketData(mode="FULL", exchangeTokens={"NSE": chunk})
            fetched = (resp or {}).get("data", {}).get("fetched", []) or []
        except Exception as e:
            print(f"  batch {i}: error {e}", file=sys.stderr)
            fetched = []
        for row in fetched:
            sym = tok_sym.get(str(row.get("symbolToken")))
            if not sym:
                continue
            try:
                high = float(row.get("high"))
                ltp = float(row.get("ltp"))  # after close, LTP = the day's close
            except (TypeError, ValueError):
                continue
            if high > 0 and ltp > 0:
                out[sym] = (round(high, 2), round(ltp, 2), _trade_date(row, fallback_date))
        time.sleep(SLEEP_BETWEEN)
    return out


def main():
    if not os.path.exists(s.SNAPSHOT_PATH):
        print("ERROR: snapshot missing — run backfill_frontier.py first.", file=sys.stderr)
        sys.exit(1)

    snap = pd.read_csv(s.SNAPSHOT_PATH)
    snap["Symbol"] = snap["Symbol"].astype(str).str.strip()
    by_sym = {r["Symbol"]: dict(r) for _, r in snap.iterrows()}

    uni = s.load_universe()
    target = set(uni["Symbol"].astype(str).str.strip().str.upper())

    obj = login()
    sym_token = token_map(target)
    print(f"mapped {len(sym_token)}/{len(target)} symbols to Angel tokens")
    if not sym_token:
        print("ERROR: no tokens mapped; aborting", file=sys.stderr)
        sys.exit(4)

    today = datetime.now(IST).strftime("%Y-%m-%d")
    quotes = fetch_quotes(obj, sym_token, today)
    frac = len(quotes) / max(1, len(sym_token))
    print(f"got quotes for {len(quotes)}/{len(sym_token)} ({frac:.0%})")
    if frac < MIN_SUCCESS_FRAC:
        print("ERROR: too few quotes; keeping yesterday's snapshot", file=sys.stderr)
        sys.exit(5)

    updated = skipped_split = stale = 0
    for sym, (high, ltp, tdate) in quotes.items():
        row = by_sym.get(sym)
        if row is None:
            continue
        # Skip only if what we stored is from a strictly NEWER day than this
        # quote. A same-day quote is allowed to refresh: a later run (e.g. after
        # close) carries the true closing price, so the last run of the day wins.
        # (The old `>=` froze the first — often pre-close — run of the day.)
        if str(row.get("LastDate")) > tdate:
            stale += 1
            continue

        prev = row.get("LastClose")
        row["LastClose"] = ltp
        row["LastDate"] = tdate

        # split/anomaly guard: don't corrupt the frontier on a suspicious gap
        try:
            ratio = ltp / float(prev) if prev and float(prev) > 0 else 1.0
        except (TypeError, ValueError):
            ratio = 1.0
        if not (RATIO_LO <= ratio <= RATIO_HI):
            skipped_split += 1
            continue

        fr = F.decode_frontier(row.get("Frontier", ""))
        # if an earlier run today already appended a point for tdate, drop it so
        # a re-run replaces (not duplicates) today's high with the latest value.
        if fr and fr[-1][0] == tdate:
            fr.pop()
        while fr and fr[-1][1] <= high:
            fr.pop()
        fr.append((tdate, high))
        ath_p, ath_d = F.ath(fr)
        row["Frontier"] = F.encode_frontier(fr)
        row["HighATH"], row["HighATHDate"] = ath_p, ath_d
        updated += 1

    if updated == 0 and skipped_split == 0:
        print(f"no newer trade date than the snapshot (stale {stale}); nothing to update")

    with contextlib.suppress(Exception):
        obj.terminateSession(_env("ANGEL_CLIENT_CODE"))

    price = pd.DataFrame(list(by_sym.values()))[
        ["Symbol", "Company", "LastClose", "AvgVol20d", "LastDate", "HighATH", "HighATHDate", "Frontier"]
    ]
    out = s.merge_reference(price)
    out.to_csv(s.SNAPSHOT_PATH, index=False)
    latest = out["LastDate"].dropna().max() if "LastDate" in out else "?"
    print(
        f"DONE: {len(out)} rows | updated {updated}, skipped(split-guard) {skipped_split} | snapshot now as of {latest}"
    )


if __name__ == "__main__":
    main()
