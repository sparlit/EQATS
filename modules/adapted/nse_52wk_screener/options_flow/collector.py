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
Live options-flow collector (runs on the VM during market hours).

Every ~2 min: pull getMarketData FULL over the scoped option tokens + the nearest
future per underlying, compute IV/Greeks (Black-76 off the future), intraday
5/10/15-min deltas (OI, price, IV, volume), the build-up label, spread and
notional, then upsert the whole enriched scan to Supabase (`options_scan`). The
Streamlit app reads that table.

  python options_flow/collector.py --once     # one cycle then exit (testing)
  python options_flow/collector.py            # continuous, market-hours aware

Env (systemd EnvironmentFile, or options_flow/.env for manual runs):
  ANGEL_API_KEY, ANGEL_CLIENT_CODE, ANGEL_PIN, ANGEL_TOTP_SECRET,
  SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from datetime import time as dtime

# --- load options_flow/.env for manual runs (systemd EnvironmentFile still wins)
_ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_ENV):
    with open(_ENV) as _f:
        for _ln in _f:
            _ln = _ln.strip()
            if _ln and not _ln.startswith("#") and "=" in _ln:
                _k, _, _v = _ln.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

import alerts
import greeks as G
import store
import universe as U

IST = timezone(timedelta(hours=5, minutes=30))
UNIVERSE_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe.json")
FULL_BATCH = 50
CYCLE_SECS = 120
BUFFER_MIN = 16  # keep ~16 min of samples for 5/10/15-min deltas
MIN_FETCH_FRAC = 0.5
OI_EPS, PX_EPS = 0.5, 0.5  # % thresholds for build-up classification


# ----------------------------------------------------------------------------
def now_ist():
    return datetime.now(IST)


def market_open(now=None):
    now = now or now_ist()
    if now.weekday() >= 5:
        return False
    return dtime(9, 15) <= now.time() <= dtime(15, 30)


def years_to_expiry(expiry_iso):
    exp = datetime.fromisoformat(expiry_iso).replace(hour=15, minute=30, second=0, tzinfo=IST)
    secs = (exp - now_ist()).total_seconds()
    return max(secs, 60.0) / (365.0 * 24 * 3600)


def angel_login():
    import pyotp
    from SmartApi import SmartConnect

    for v in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"):
        if not os.getenv(v):
            print(f"ERROR: missing env {v}", file=sys.stderr)
            sys.exit(2)
    obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    totp = pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
    sess = obj.generateSession(os.getenv("ANGEL_CLIENT_CODE"), os.getenv("ANGEL_PIN"), totp)
    if not sess or not sess.get("status"):
        print(f"ERROR: Angel login failed: {sess}", file=sys.stderr)
        sys.exit(3)
    return obj


def fetch_full(obj, tokens):
    """token -> raw getMarketData FULL row."""
    out = {}
    for i in range(0, len(tokens), FULL_BATCH):
        chunk = tokens[i : i + FULL_BATCH]
        try:
            resp = obj.getMarketData(mode="FULL", exchangeTokens={"NFO": chunk})
            for row in (resp or {}).get("data", {}).get("fetched", []) or []:
                out[str(row.get("symbolToken"))] = row
        except Exception as e:
            print(f"  batch {i}: {e}", file=sys.stderr)
        time.sleep(1.0)  # respect ~1 req/s
    return out


def _f(row, key):
    try:
        v = row.get(key)
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _spread_pct(row):
    d = row.get("depth") or {}
    try:
        bid = float(d.get("buy", [{}])[0].get("price"))
        ask = float(d.get("sell", [{}])[0].get("price"))
        if bid > 0 and ask > 0:
            return round((ask - bid) / ((ask + bid) / 2) * 100, 2)
    except (TypeError, ValueError, IndexError):
        pass
    return None


def _buildup(px_chg_pct, oi_chg_pct):
    if px_chg_pct is None or oi_chg_pct is None:
        return None
    if abs(px_chg_pct) < PX_EPS or abs(oi_chg_pct) < OI_EPS:
        return "Neutral"
    up_px, up_oi = px_chg_pct > 0, oi_chg_pct > 0
    if up_px and up_oi:
        return "Long Buildup"
    if not up_px and up_oi:
        return "Short Buildup"
    if up_px and not up_oi:
        return "Short Covering"
    return "Long Unwinding"


def _ago(buf, minutes, key):
    """Value of `key` from the sample closest to `minutes` ago (±70s), else None."""
    if not buf:
        return None
    target = time.time() - minutes * 60
    best, bestd = None, 71
    for s in buf:
        d = abs(s["t"] - target)
        if d < bestd:
            best, bestd = s, d
    return best[key] if best else None


# ----------------------------------------------------------------------------
def run_cycle(obj, uni, buffer, day_open, alert_state):
    fetched = fetch_full(obj, uni["tokens"])
    if len(fetched) < MIN_FETCH_FRAC * len(uni["tokens"]):
        print(
            f"  only {len(fetched)}/{len(uni['tokens'])} fetched — skipping upsert", file=sys.stderr
        )
        return 0

    forward = {}
    for name, fut in uni["futures"].items():
        r = fetched.get(fut["token"])
        if r:
            forward[name] = _f(r, "ltp")

    as_of = now_ist().isoformat()
    rows = []
    for opt in uni["options"]:
        tok = opt["token"]
        row = fetched.get(tok)
        if not row:
            continue
        ltp = _f(row, "ltp")
        oi = _f(row, "opnInterest")
        vol = _f(row, "tradeVolume")
        prev_close = _f(row, "close")
        if ltp is None or oi is None:
            continue
        F = forward.get(opt["underlying"])
        T = years_to_expiry(opt["expiry"])
        iv, gk = (
            G.iv_and_greeks(opt["type"], ltp, F, opt["strike"], T)
            if F
            else (None, {"delta": None, "gamma": None, "vega": None})
        )

        d0 = day_open.setdefault(tok, {"oi": oi, "ltp": ltp})
        buf = buffer.setdefault(tok, [])

        oi5, oi10, oi15 = (_ago(buf, 5, "oi"), _ago(buf, 10, "oi"), _ago(buf, 15, "oi"))
        px5, px10, px15 = (_ago(buf, 5, "ltp"), _ago(buf, 10, "ltp"), _ago(buf, 15, "ltp"))
        iv5, iv10, iv15 = (_ago(buf, 5, "iv"), _ago(buf, 10, "iv"), _ago(buf, 15, "iv"))
        v5, v10, v15 = (_ago(buf, 5, "vol"), _ago(buf, 10, "vol"), _ago(buf, 15, "vol"))

        def _pct(now_v, then_v):
            return round((now_v - then_v) / then_v * 100, 2) if then_v else None

        chg_pct = _pct(ltp, prev_close)
        oi_chg_day = int(oi - d0["oi"])
        oi_chg_day_pct = _pct(oi, d0["oi"])

        rows.append(
            {
                "token": tok,
                "as_of": as_of,
                "symbol": opt["symbol"],
                "underlying": opt["underlying"],
                "kind": opt["type"],
                "strike": opt["strike"],
                "expiry": opt["expiry"],
                "dte": opt["dte"],
                "ltp": ltp,
                "chg_pct": chg_pct,
                "oi": int(oi),
                "oi_chg_day": oi_chg_day,
                "oi_chg_day_pct": oi_chg_day_pct,
                "volume": int(vol) if vol is not None else None,
                "vol_oi": round(vol / oi, 3) if (vol and oi) else None,
                "notional": round(ltp * vol, 0) if (ltp and vol) else None,
                "iv": round(iv * 100, 2) if iv else None,
                "delta": gk["delta"],
                "gamma": gk["gamma"],
                "vega": gk["vega"],
                "d5_oi": int(oi - oi5) if oi5 is not None else None,
                "d10_oi": int(oi - oi10) if oi10 is not None else None,
                "d15_oi": int(oi - oi15) if oi15 is not None else None,
                "d5_price_pct": _pct(ltp, px5),
                "d10_price_pct": _pct(ltp, px10),
                "d15_price_pct": _pct(ltp, px15),
                "d5_iv": round(iv * 100 - iv5, 2) if (iv and iv5 is not None) else None,
                "d10_iv": round(iv * 100 - iv10, 2) if (iv and iv10 is not None) else None,
                "d15_iv": round(iv * 100 - iv15, 2) if (iv and iv15 is not None) else None,
                "d5_vol": int(vol - v5) if (vol is not None and v5 is not None) else None,
                "d10_vol": int(vol - v10) if (vol is not None and v10 is not None) else None,
                "d15_vol": int(vol - v15) if (vol is not None and v15 is not None) else None,
                "buildup": _buildup(chg_pct, oi_chg_day_pct),
                "spread_pct": _spread_pct(row),
                "forward": round(F, 2) if F else None,
            }
        )

        buf.append(
            {"t": time.time(), "oi": oi, "ltp": ltp, "vol": vol, "iv": iv * 100 if iv else None}
        )
        cutoff = time.time() - BUFFER_MIN * 60
        while buf and buf[0]["t"] < cutoff:
            buf.pop(0)

    n = store.upsert_scan(rows)
    # Drop tokens no longer in the universe (expiry rolled, ATM drifted) so the
    # table stays ≈ the current universe instead of accumulating dead contracts.
    try:
        store.prune_stale((now_ist() - timedelta(minutes=10)).isoformat())
    except Exception as e:
        print(f"  prune skipped: {e}", file=sys.stderr)
    try:
        pushed = alerts.maybe_push(rows, alert_state)
        if pushed:
            print(f"  pushed {pushed} alert(s) to Telegram", flush=True)
    except Exception as e:
        print(f"  alerts skipped: {e}", file=sys.stderr)
    print(
        f"[{now_ist():%H:%M:%S}] fetched {len(fetched)}/{len(uni['tokens'])} "
        f"-> upserted {n} contracts",
        flush=True,
    )
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one cycle then exit")
    ap.add_argument("--strikes", type=int, default=15)
    args = ap.parse_args()

    print("building scoped universe…", flush=True)
    uni = U.build(strikes_each_side=args.strikes, cache_path=UNIVERSE_CACHE)
    print(
        f"  options={uni['meta']['n_options']} futures={uni['meta']['n_futures']} "
        f"tokens={len(uni['tokens'])} missing={uni['meta']['missing']}",
        flush=True,
    )

    obj = angel_login()
    buffer, day_open, alert_state, cur_day = {}, {}, {}, now_ist().date()
    if alerts.configured():
        print("  Telegram alerts: ON", flush=True)

    while True:
        if not market_open():
            if args.once:
                print("market closed — running one cycle anyway for a smoke test.", flush=True)
            else:
                print(f"[{now_ist():%H:%M}] market closed — idle.", flush=True)
                time.sleep(60)
                continue
        if now_ist().date() != cur_day:  # new trading day → rebuild + reset
            uni = U.build(strikes_each_side=args.strikes, cache_path=UNIVERSE_CACHE)
            buffer, day_open, alert_state, cur_day = {}, {}, {}, now_ist().date()

        t0 = time.time()
        try:
            run_cycle(obj, uni, buffer, day_open, alert_state)
        except Exception as e:
            print(f"cycle error: {e}", file=sys.stderr, flush=True)
        if args.once:
            break
        time.sleep(max(5.0, CYCLE_SECS - (time.time() - t0)))


if __name__ == "__main__":
    main()
