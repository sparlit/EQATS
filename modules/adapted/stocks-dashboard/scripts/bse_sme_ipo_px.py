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


# -*- coding: utf-8 -*-
"""BSE SME IPO price ledger — every member's BSE bhavcopy bars 2020→, kept in the repo so CI can refresh the
"Every member, ever" table nightly without a local bhavcopy cache  (runbook §195).

LEDGER  scripts/bse_sme_ipo_px.json.gz
        {"end": YYYYMMDD, "built": ISO, "px": {code: {"d":[YYYYMMDD…], "rc":[raw close…], "v":[shares…],
                                                     "isd":[[i, isin]…], "g":[[i, group]…], "tk": id}}}
        isd / g are CHANGE lists (index where the ISIN / BSE group changes) — the per-bar arrays build_series
        produces, run-length encoded.
CODES   every scrip in docs/bse_sme_ipo/stints.json + BSE's current official list (members.json) — a new member is
        picked up the day it appears; a past member keeps getting bars (its life after leaving the index / after a
        migration to the main board is part of the table).
SOURCE  BSE daily bhavcopies through build_bse_sme_backfill (same parser, same date-inside-the-file check, same
        adjustment: adjust_series()).

  build    BSE_BHAV_CACHE=~/stocks-cache/bse_bhav python3 scripts/bse_sme_ipo_px.py build    (local, from the cache)
  update   python3 scripts/bse_sme_ipo_px.py update    (CI: fetch only the days after "end" into a temp dir, append)
  series(codes) -> {code: series} in build_series() shape (d, rc, c, v, splits, unexpl, first_sme, last_sme, …)
"""
import datetime
import gzip
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contextlib

import build_bse_sme_backfill as BB

ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(HERE, "bse_sme_ipo_px.json.gz")
DOCS = os.path.join(ROOT, "docs")
START = 20200101


def member_codes():
    codes = set()
    with contextlib.suppress(FileNotFoundError):
        codes |= {
            s["code"]
            for s in json.load(open(os.path.join(DOCS, "bse_sme_ipo", "stints.json")))["stints"]
        }
    with contextlib.suppress(FileNotFoundError):
        codes |= {
            m["code"]
            for m in json.load(open(os.path.join(DOCS, "bse_sme_ipo", "members.json")))["members"]
        }
    return codes


def rle(vals):
    out = []
    for i, v in enumerate(vals):
        if not out or out[-1][1] != v:
            out.append([i, v])
    return out


def unrle(pairs, n):
    out = []
    for j, (i, v) in enumerate(pairs):
        end = pairs[j + 1][0] if j + 1 < len(pairs) else n
        out += [v] * (end - i)
    return out


def load():
    try:
        return json.loads(gzip.decompress(open(LEDGER, "rb").read()))
    except FileNotFoundError:
        return {"end": 0, "px": {}}


def save(L):
    L["built"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    blob = json.dumps(L, separators=(",", ":"), sort_keys=True).encode()
    tmp = LEDGER + ".tmp"
    with open(tmp, "wb") as f:
        f.write(gzip.compress(blob, 9))
    os.replace(tmp, LEDGER)


def append_day(L, k, rows, codes):
    """rows = BB.rows_of() output for day k; appends a bar for every tracked code that traded (close > 0)."""
    n = 0
    for code, g, c, _pc, v, isin, tk in rows:
        if code not in codes or c <= 0:
            continue
        e = L["px"].get(code)
        if e is None:
            e = L["px"][code] = {"d": [], "rc": [], "v": [], "isd": [], "g": [], "tk": tk}
        if e["d"] and e["d"][-1] >= k:
            continue
        i = len(e["d"])
        e["d"].append(k)
        e["rc"].append(c)
        e["v"].append(v)
        isin = isin or (e["isd"][-1][1] if e["isd"] else "")
        if not e["isd"] or e["isd"][-1][1] != isin:
            e["isd"].append([i, isin])
        if not e["g"] or e["g"][-1][1] != g:
            e["g"].append([i, g])
        e["tk"] = tk or e["tk"]
        n += 1
    L["end"] = max(L.get("end") or 0, k)
    return n


def build():
    codes = member_codes()
    files = sorted(f for f in os.listdir(BB.CACHE) if f[:8].isdigit() and int(f[:8]) >= START)
    L = {"end": 0, "px": {}}
    prev_sig = None
    used = dropped = 0
    for f in files:
        k = int(f[:8])
        rs = BB.rows_of(k, os.path.join(BB.CACHE, f))
        if rs is None:
            dropped += 1
            continue
        sig = hash(tuple(rs))
        if sig == prev_sig:
            dropped += 1
            continue
        prev_sig = sig
        append_day(L, k, rs, codes)
        used += 1
    save(L)
    print(
        "ledger build: %d day files (%d re-served dropped), %d of %d codes with bars, end %d → %s (%d bytes)"
        % (used, dropped, len(L["px"]), len(codes), L["end"], LEDGER, os.path.getsize(LEDGER))
    )


def update(max_days=40):
    L = load()
    if not L["px"]:
        sys.exit("no ledger to update — run `build` locally first")
    codes = member_codes()
    end = L["end"]
    frm = datetime.datetime.strptime(str(end), "%Y%m%d").date() + datetime.timedelta(1)
    to = datetime.date.today()
    if (to - frm).days > max_days:
        sys.exit(
            "ledger ends %d — more than %d days behind; rebuild locally instead" % (end, max_days)
        )
    tmp = tempfile.mkdtemp(prefix="bsebhav_")
    BB.CACHE = tmp
    BB.MISS = os.path.join(tmp, "_absent.json")  # fetch() reads these module globals
    try:
        BB.fetch(int(frm.strftime("%Y%m%d")), int(to.strftime("%Y%m%d")))
    except BB.Blocked as e:
        sys.exit(f"BSE blocked the bhavcopy download: {e}")
    added = 0
    days = 0
    for f in sorted(x for x in os.listdir(tmp) if x[:8].isdigit()):
        k = int(f[:8])
        if k <= end:
            continue
        rs = BB.rows_of(k, os.path.join(tmp, f))
        if rs is None:
            print("  %d: file stamped with another day — dropped (§89f)" % k)
            continue
        added += append_day(L, k, rs, codes)
        days += 1
    new_codes = sorted(c for c in codes if c not in L["px"])
    save(L)
    print(
        "ledger update: %d new day(s) after %d, %d bars appended, end now %d; %d tracked code(s) with no bar yet %s"
        % (days, end, added, L["end"], len(new_codes), new_codes[:10])
    )


def series(codes=None):
    L = load()
    out = {}
    for code, e in L["px"].items():
        if codes is not None and code not in codes:
            continue
        n = len(e["d"])
        isd = unrle(e["isd"], n)
        g = unrle(e["g"], n)
        out[code] = {
            "d": list(e["d"]),
            "rc": list(e["rc"]),
            "isd": isd,
            "v": list(e["v"]),
            "g": g,
            "isin": next((x for x in reversed(isd) if x), ""),
            "tk": e.get("tk"),
        }
    return BB.adjust_series(out), L["end"]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        build()
    elif cmd == "update":
        update()
    else:
        sys.exit(__doc__)
