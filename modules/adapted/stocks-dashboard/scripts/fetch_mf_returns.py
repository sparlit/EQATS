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


#!/usr/bin/env python3
"""Refresh returns for the mutual-fund universe (Direct-Growth plans).

Designed to run unattended in CI (GitHub Actions) with no external inputs.

UNIVERSE = (existing scripts/mutual_funds.json)  ∪  (AMFI active Direct-Growth):
  - Existing funds keep their identity (category/name/AMC/ISIN stay stable).
  - AMFI's daily NAVAll file is parsed for every currently-active Direct-Growth
    scheme; any not already present is ADDED (category from AMFI's SEBI section
    header). Segregated side-pocket portfolios are skipped. This way newly
    launched funds — and funds that were missing from the original seed —
    self-heal into the dashboard automatically.

Each scheme's full NAV history is fetched from mfapi.in to compute returns at
1d / 1w / 1m / 3m / 6m / 1y / 3y / 5y / 10y + since inception.

Resilience: a scheme that fails to fetch (mfapi hiccup / rate-limit) keeps its
PREVIOUS record instead of being dropped, so the universe never shrinks on a
transient error. If AMFI is unreachable, discovery is skipped and the existing
universe is simply refreshed.

Sources: AMFI NAVAll.txt (scheme master) + mfapi.in (full NAV history).
Output: scripts/mutual_funds.json
"""
import base64
import gzip
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "scripts" / "mutual_funds.json"

if not OUT.exists():
    msg = f"Seed file {OUT} not found — cannot determine fund universe."
    raise SystemExit(msg)

existing = json.loads(OUT.read_text(encoding="utf-8"))
OLD = {r["code"]: r for r in existing}


# ---------------------------------------------------------------------------
# Growth-plan filter (both Direct and Regular) + plan tag + side-pocket detector
# ---------------------------------------------------------------------------
def is_growth(n):
    n = n.lower()
    return (
        "growth" in n
        and "idcw" not in n
        and "dividend" not in n
        and "payout" not in n
        and "reinvest" not in n
        and "bonus" not in n
    )


def plan_of(name):
    # Regular plans (incl. older funds named just "... - Growth") give the
    # fund's TRUE pre-2013 history; Direct plans only exist from Jan 2013.
    return "Direct" if "direct" in name.lower() else "Regular"


def is_segregated(n):
    n = n.lower()
    return "segregat" in n or "seg." in n or "portfolio" in n or "side pocket" in n or "side-pocket" in n


def clean_short(name):
    for suf in (
        " - DIRECT - Growth",
        " - Direct Plan - Growth Option",
        " - Direct Plan - Growth",
        " Direct Plan-Growth",
        " Direct - Growth",
        "- Direct (G)",
        " - Direct – Growth",
        " -Direct - Growth",
        "-Direct Plan-Growth",
        " - Regular Plan - Growth Option",
        " - Regular Plan - Growth",
        " Regular Plan-Growth",
        " - REGULAR - Growth",
        "- Regular (G)",
        " - Growth Option",
        " - Growth Plan",
        " - Growth",
    ):
        name = name.replace(suf, "")
    return name.strip()


# ---------------------------------------------------------------------------
# Discover AMFI's current active Direct-Growth universe (best-effort)
# ---------------------------------------------------------------------------
def discover_amfi():
    """Return {code(str): {'name':..., 'category':...}} for active Direct-Growth
    schemes (excluding segregated side-pockets). Empty dict on any failure."""
    url = "https://www.amfiindia.com/spages/NAVAll.txt"
    txt = ""
    # Primary: urllib (portable, works on Windows + CI). Fallback: curl.
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        txt = urllib.request.urlopen(req, timeout=70).read().decode("utf-8", "ignore")
    except Exception:
        try:
            r = subprocess.run(
                ["curl", "-s", "--max-time", "60", "-A", "Mozilla/5.0", url], capture_output=True, timeout=70
            )
            txt = r.stdout.decode("utf-8", errors="ignore")
        except Exception:
            return {}
    if not txt:
        return {}
    out, cat = {}, None
    for ln in txt.splitlines():
        if ";" in ln:
            p = ln.split(";")
            if len(p) >= 5 and p[0].strip().isdigit():
                name = p[3].strip()
                if is_growth(name) and not is_segregated(name):
                    out[p[0].strip()] = {"name": name, "category": cat}
        else:
            s = ln.strip()
            m = re.search(r"\((.*)\)\s*$", s)
            if m and "Scheme" in s:
                cat = m.group(1).strip()
    return out


# Build merged universe: existing first (identity preserved), then AMFI new ones.
SCHEMES = []
seen = set()
for rec in existing:
    SCHEMES.append(
        {
            "code": rec["code"],
            "name": rec["name"],
            "short": rec.get("short"),
            "amc": rec.get("amc"),
            "category": rec.get("category"),
            "isin": rec.get("isin", ""),
            "plan": rec.get("plan") or plan_of(rec["name"]),
        }
    )
    seen.add(str(rec["code"]))

amfi = discover_amfi()
new_funds = new_regular = 0
for code, info in amfi.items():
    if code in seen:
        continue
    pl = plan_of(info["name"])
    SCHEMES.append(
        {
            "code": int(code),
            "name": info["name"],
            "short": clean_short(info["name"]),
            "amc": None,
            "category": info["category"],
            "isin": "",
            "plan": pl,
        }
    )
    seen.add(code)
    new_funds += 1
    if pl == "Regular":
        new_regular += 1

print(
    f"Universe: {len(existing)} existing + {new_funds} newly discovered from AMFI "
    f"({new_regular} of them Regular plans) = {len(SCHEMES)} total"
)

# Optional cap for local testing: MF_LIMIT=20 python scripts/fetch_mf_returns.py
LIMIT = int(os.environ.get("MF_LIMIT", "0") or "0")
if LIMIT > 0:
    SCHEMES = SCHEMES[:LIMIT]

print(f"Refreshing {len(SCHEMES)} schemes (returns at 1d/1w/1m/3m/6m/1y/3y/5y/10y/inception)...")

LOOKBACKS_DAYS = {
    "r1d": 1,
    "r1w": 7,
    "r1m": 30,
    "r3m": 91,
    "r6m": 182,
    "r1y": 365,
    "r3y": 3 * 365,
    "r5y": 5 * 365,
    "r10y": 10 * 365,
}
# Maximum gap between requested lookback and the actual NAV we matched. Beyond
# this we return null — otherwise sparse-NAV schemes (segregated side-pockets,
# illiquid debt) would show the SAME return at every horizon because every
# lookback finds the same single old NAV point.
STALENESS_TOLERANCE_DAYS = {
    "r1d": 7,
    "r1w": 7,
    "r1m": 30,
    "r3m": 30,
    "r6m": 60,
    "r1y": 60,
    "r3y": 180,
    "r5y": 180,
    "r10y": 180,
}
ANNUALIZE_AFTER_DAYS = 365  # any period > 1 year is reported as CAGR
STALE_AFTER_DAYS = 5  # latest NAV older than this -> flag the fund "stale"


def nav_at_or_before(data, target_dt):
    """data is descending by date. Return (nav, date) at the most recent date
    that is <= target_dt, or None if no such date exists."""
    for entry in data:
        try:
            d = datetime.strptime(entry["date"], "%d-%m-%Y")
        except Exception:
            continue
        if d <= target_dt:
            try:
                v = float(entry["nav"])
                return (v, d) if v > 0 else None
            except Exception:
                return None
    return None


def _get(code, attempts=5):
    """Fetch a scheme's NAV JSON from mfapi with retries + backoff, to ride out
    transient timeouts / rate-limits. Returns the parsed dict, or None only if
    every attempt failed (genuinely no data)."""
    for i in range(attempts):
        try:
            r = subprocess.run(
                ["curl", "-s", "--max-time", "25", f"https://api.mfapi.in/mf/{code}"], capture_output=True, timeout=30
            )
            d = json.loads(r.stdout.decode("utf-8", errors="ignore"))
            if d.get("status") == "SUCCESS" and d.get("data"):
                return d
        except Exception:
            pass
        time.sleep(0.4 * (i + 1))
    return None


def fetch_one(scheme):
    code = scheme["code"]
    try:
        d = _get(code)
        if not d:
            return None
        data = d["data"]  # newest first
        # Guard against NAV redenominations / spliced histories: some scheme
        # codes have a one-day NAV jump of 10x-100x (a restated NAV base, e.g.
        # several overnight funds on 2018-05-03) or splice in an unrelated older
        # fund's NAVs. Such discontinuities wreck since-inception & 10Y returns.
        # Keep only the clean segment AFTER the most recent implausible jump.
        chron = list(reversed(data))  # oldest -> newest
        cut = 0
        for i in range(1, len(chron)):
            try:
                pv = float(chron[i - 1]["nav"])
                cv = float(chron[i]["nav"])
            except Exception:
                continue
            if pv > 0 and (cv / pv > 1.5 or cv / pv < 0.667):
                cut = i  # a real fund never moves >50% in a single day
        if cut:
            data = list(reversed(chron[cut:]))
        if not data:
            return None
        latest = data[0]
        nav_latest = float(latest["nav"])
        if nav_latest <= 0:
            return None
        d_lat = datetime.strptime(latest["date"], "%d-%m-%Y")

        # Inception
        inception = data[-1]
        nav_inc = float(inception["nav"])
        if nav_inc <= 0:
            return None
        d_inc = datetime.strptime(inception["date"], "%d-%m-%Y")
        inc_days = (d_lat - d_inc).days
        inc_years = inc_days / 365.25
        inc_total = (nav_latest - nav_inc) / nav_inc * 100
        # Don't annualize for funds under 1 year old — annualizing a sub-year
        # return wildly exaggerates it (SEBI shows absolute returns for <1yr).
        inc_cagr = ((nav_latest / nav_inc) ** (1 / inc_years) - 1) * 100 if inc_years >= 1.0 else inc_total

        # Returns at each lookback
        returns = {}
        for label, days in LOOKBACKS_DAYS.items():
            if inc_days < days:
                returns[label] = None
                continue
            target = d_lat - timedelta(days=days)
            hit = nav_at_or_before(data, target)
            if hit is None:
                returns[label] = None
                continue
            nav_then, d_then = hit
            actual_days = (d_lat - d_then).days
            if actual_days < 1:
                returns[label] = None
                continue
            if actual_days > days + STALENESS_TOLERANCE_DAYS[label]:
                returns[label] = None
                continue
            if days <= ANNUALIZE_AFTER_DAYS:
                returns[label] = round((nav_latest - nav_then) / nav_then * 100, 2)
            else:
                yrs = actual_days / 365.25
                cagr = ((nav_latest / nav_then) ** (1 / yrs) - 1) * 100
                returns[label] = round(cagr, 2)

        # Full DAILY NAV history (for the exact-date return calculator), as
        # parallel arrays of YYYYMMDD ints + paise ints (NAV*100). Uses the
        # clean post-splice-trim series. build packs these to a shared axis.
        hdays, hnavs = [], []
        for x in reversed(data):  # oldest -> newest
            try:
                dt = datetime.strptime(x["date"], "%d-%m-%Y")
                pv = round(float(x["nav"]) * 100)
            except Exception:
                continue
            if pv > 0:
                hdays.append(dt.year * 10000 + dt.month * 100 + dt.day)
                hnavs.append(pv)

        meta = d.get("meta", {})
        stale_days = (datetime.now(UTC).replace(tzinfo=None) - d_lat).days
        return {
            "_d": hdays,
            "_n": hnavs,
            "code": code,
            "name": scheme["name"],
            # Keep the already-cleaned short label / AMC / category / isin from the
            # seed record; for newly discovered funds these come from AMFI + mfapi.
            "short": scheme.get("short") or clean_short(scheme["name"]),
            "amc": scheme.get("amc") or meta.get("fund_house"),
            "category": scheme.get("category") or meta.get("scheme_category"),
            "isin": scheme.get("isin", ""),
            "plan": scheme.get("plan") or plan_of(scheme["name"]),
            "inceptionDate": d_inc.strftime("%Y-%m-%d"),
            "latestDate": d_lat.strftime("%Y-%m-%d"),
            "inceptionNav": round(nav_inc, 4),
            "latestNav": round(nav_latest, 4),
            "totalReturnPct": round(inc_total, 2),
            "cagrPct": round(inc_cagr, 2),
            "years": round(inc_years, 2),
            "stale": stale_days > STALE_AFTER_DAYS,
            "staleDays": max(stale_days, 0),
            **returns,
        }
    except Exception:
        return None


by_code = {}  # code -> record (fresh wins; dict dedupes)
fresh = set()  # codes we got FRESH data for this run
BATCH = 200
for batch_start in range(0, len(SCHEMES), BATCH):
    chunk = SCHEMES[batch_start : batch_start + BATCH]
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = {pool.submit(fetch_one, s): s for s in chunk}
        for fut in as_completed(futs):
            r = fut.result()
            code = futs[fut]["code"]
            if r is not None:
                by_code[code] = r
                fresh.add(code)
            elif code not in by_code and OLD.get(code) is not None:
                by_code[code] = OLD[code]  # provisional: keep old until a retry succeeds
    done = min(batch_start + BATCH, len(SCHEMES))
    print(
        f"  [{done}/{len(SCHEMES)}]  fresh={len(fresh)} "
        f"kept-stale={len(by_code) - len(fresh)} missing={len(SCHEMES) - len(by_code)}",
        flush=True,
    )

# ---- None-left-behind retry passes -----------------------------------------
# Anything not yet FRESH (a transient failure, or a kept-stale record) gets
# re-tried with gentler concurrency to dodge mfapi rate-limits. Repeat until a
# pass recovers nothing, so we don't silently drop / stale-out funds.
if not LIMIT:
    for rnd in range(1, 6):
        todo = [s for s in SCHEMES if s["code"] not in fresh]
        if not todo:
            break
        print(f"Retry pass {rnd}: {len(todo)} not-yet-fresh schemes...", flush=True)
        got = 0
        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = {pool.submit(fetch_one, s): s for s in todo}
            for fut in as_completed(futs):
                r = fut.result()
                if r is not None:
                    by_code[futs[fut]["code"]] = r
                    fresh.add(futs[fut]["code"])
                    got += 1
        print(f"  recovered {got}", flush=True)
        if got == 0:
            break
    unfetchable = [s for s in SCHEMES if s["code"] not in by_code]
    print(f"Unfetchable (no data on mfapi even after retries): {len(unfetchable)}")
    for s in unfetchable[:50]:
        print(f"   {s['code']}  {s['name'][:55]}")
else:
    for r in existing:  # MF_LIMIT test: keep the untouched rest
        if r["code"] not in by_code:
            by_code[r["code"]] = r

results = list(by_code.values())
kept = len(results) - len(fresh)
print(f"\nDone: {len(fresh)} fresh, {kept} kept stale -> {len(results)} total")

# Build the DAILY history payload for the exact-date calculator: a shared
# trading-day axis (YYYYMMDD ints) + per-fund [startIdx, delta-encoded paise].
# Delta encoding + gzip keeps a ~20-year daily series for ~5k funds compact.
# Written pre-gzipped+base64 so build just embeds it. Kept-stale records have
# no fresh history. (File is gitignored — a build intermediate.)
HISTB64 = ROOT / "scripts" / "mf_history.b64"
series, alldates = {}, set()
for r in results:
    dd = r.pop("_d", None)
    nn = r.pop("_n", None)
    if dd and nn:
        series[str(r["code"])] = (dd, nn)
        alldates.update(dd)
axis = sorted(alldates)
aidx = {d: i for i, d in enumerate(axis)}
packed = {}
for code, (dd, nn) in series.items():
    navmap = dict(zip(dd, nn, strict=False))
    s, e = aidx[dd[0]], aidx[dd[-1]]
    arr, last = [], None
    for i in range(s, e + 1):
        d = axis[i]
        if d in navmap:
            last = navmap[d]
        arr.append(last)
    deltas = [arr[0]]
    for k in range(1, len(arr)):
        deltas.append(arr[k] - arr[k - 1])
    packed[code] = [s, *deltas]
hraw = json.dumps({"dates": axis, "data": packed}, separators=(",", ":")).encode()
hgz = gzip.compress(hraw, compresslevel=9)
HISTB64.write_text(base64.b64encode(hgz).decode(), encoding="utf-8")
# Also write the raw gzip as a docs/ asset the backtest page fetches directly.
(ROOT / "docs" / "mf_history.bin").write_bytes(hgz)
print(
    f"Saved -> {HISTB64}  ({HISTB64.stat().st_size / 1024 / 1024:.1f} MB b64, "
    f"{len(packed)} funds, {len(axis)} trading days)  + docs/mf_history.bin"
)

results.sort(key=lambda r: -(r.get("cagrPct") or 0))
OUT.write_text(json.dumps(results, separators=(",", ":")), encoding="utf-8")
print(f"Saved -> {OUT}  ({OUT.stat().st_size / 1024:.1f} KB)")

# Slim fund list for the backtest page's picker (docs/ asset).
slim = [
    {
        "code": r["code"],
        "short": r["short"],
        "plan": r.get("plan", "Direct"),
        "category": r.get("category", ""),
        "years": r.get("years"),
        "amc": r.get("amc"),
    }
    for r in results
]
(ROOT / "docs" / "mf_funds.json").write_text(json.dumps(slim, separators=(",", ":")), encoding="utf-8")

# Re-inject the synthetic "Gold (INR, since 2006)" instrument into the backtest
# data so the Rotation tools keep gold history after every refresh. Never let a
# gold-fetch hiccup break the main pipeline.
try:
    import add_gold_instrument

    print("Injecting synthetic gold instrument for backtest…")
    add_gold_instrument.main()
except Exception as _e:
    print("  ! gold injection skipped:", _e)
