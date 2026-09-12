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
"""WEEKLY auto-detector of PHANTOM corporate actions.

Rule (user's): a big single-day price move that *matches a split/bonus ratio* but has **NO corporate
announcement** is a CRASH/correction, NOT a corporate action — its drop must be KEPT, not divided out
of the price history. (Unannounced crashes mis-read as splits silently mis-scale all pre-crash history
-> wrong 52w-high/low, drawdown, returns. e.g. REC 2024-06-04 election crash read as a 0.75 bonus.)

What it does: scans the last `lookback` days of NSE bhavcopies; for every EQ move whose ratio matches a
split/bonus factor, with (a) NO official split/bonus in corp_actions.json and (b) NO split/bonus/rights/
demerger ANNOUNCEMENT in NSE's corporate-actions feed, records (sym, exDate) as a crash and APPENDS it to
scripts/phantom_crashes.json. build_corp_actions.py (-> noadjust) and update_sf_data.py (self_heal) both
read that file, so the next daily build keeps the drop. Idempotent (only new pairs are appended).

Run (CI, weekly):  python -X utf8 audit_phantom_ca.py [lookback_days=120]
"""
import csv
import datetime
import io
import json
import os
import subprocess
import sys
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_fundamentals as F  # NSE cookie jar + _get + iso()

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122 Safari/537.36"
CA_FRACS = [
    1 / 2,
    1 / 3,
    2 / 3,
    1 / 4,
    3 / 4,
    1 / 5,
    2 / 5,
    3 / 5,
    1 / 6,
    5 / 6,
    1 / 8,
    1 / 10,
    1 / 20,
    1 / 50,
    2.0,
    3.0,
    4.0,
    5.0,
    10.0,
]


def ca_factor(r):
    if 0.75 <= r <= 1.30:
        return 1.0
    for f in CA_FRACS:
        if abs(r / f - 1) <= 0.08:
            return f
    return 1.0


KW = (
    "split",
    "sub-division",
    "sub division",
    "bonus",
    "consolidat",
    "rights",
    "demerger",
    "de-merger",
    "scheme",
    "spin",
    "reduction of capital",
    "capital reduction",
    "arrangement",
)
LOOKBACK = int(sys.argv[1]) if len(sys.argv) > 1 else 120
PC = os.path.join(HERE, "phantom_crashes.json")


def bhav(dt):
    url = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{}.csv".format(dt.strftime("%d%m%Y"))
    for _ in range(2):
        try:
            r = subprocess.run(
                ["curl", "-sL", "-A", UA, "-H", "Referer: https://www.nseindia.com/", "--max-time", "30", url],
                capture_output=True,
                timeout=45,
            )
            if len(r.stdout) > 2000:
                return r.stdout.decode("utf-8", "ignore")
        except Exception:
            pass
        time.sleep(0.8)
    return None


# official split/bonus factors already known (don't re-flag real, parsed actions)
try:
    OFFF = {
        s: {int(e[0]) for e in v}
        for s, v in json.load(open(os.path.join(HERE, "corp_actions.json"))).get("factors", {}).items()
    }
except Exception:
    OFFF = {}

# announcement map from NSE (this + last 2 years covers any move inside the lookback window) -> {sym:[(exYmd,subject)]}
jar = F.nse_jar()
h = {"User-Agent": F.UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
ANN = defaultdict(list)
yr = datetime.date.today().year
for y in (yr - 2, yr - 1, yr):
    try:
        d = json.loads(
            F._get(
                "https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=01-01-%d&to_date=31-12-%d"
                % (y, y),
                headers=h,
                jar=jar,
                timeout=40,
            )
        )
        rows = d if isinstance(d, list) else d.get("data", [])
    except Exception as e:
        print("  CA fetch %d failed: %s" % (y, str(e)[:50]))
        rows = []
    for r in rows:
        ex = F.iso(r.get("exDate"))
        if ex:
            ANN[r.get("symbol")].append((int(ex), (r.get("subject") or r.get("purpose") or "")))
    time.sleep(0.4)


def announced(sym, ymd):
    return any(abs(e - ymd) <= 7 and any(k in s.lower() for k in KW) for e, s in ANN.get(sym, []))


# scan the recent window
end = datetime.date.today()
cur = end - datetime.timedelta(days=LOOKBACK)
cands = []
# ALL calendar days: weekend special sessions (budget Saturdays, muhurat, DR Saturdays) are real
# trading days that now carry bars in the price series, so they must be audited too.
# Two traps on non-trading dates, both seen live on 2026-08-01/02:
#   1. the URL serves NSE's HTML error page (3.5 KB, passes bhav()'s size check) — reject anything
#      without a SYMBOL header, else csv.reader happily parses markup;
#   2. the URL re-serves the PRIOR session's file under the wrong date — skip a file identical to
#      the last ACCEPTED one. The signature must only advance on a genuinely parsed bhavcopy: an
#      interposed error page in between would otherwise reset the baseline and let the re-served
#      file through as a "new" session (that injected fake 2026-08-02 crashes in testing).
last_sig = None
while cur <= end:
    txt = bhav(cur)
    if txt and "SYMBOL" in txt[:200].upper():
        rows = list(csv.reader(io.StringIO(txt)))
        if rows and len(rows) > 1:
            hdr = [x.strip() for x in rows[0]]
            try:
                iS, iSer, iC, iP = (
                    hdr.index("SYMBOL"),
                    hdr.index("SERIES"),
                    hdr.index("CLOSE_PRICE"),
                    hdr.index("PREV_CLOSE"),
                )
            except ValueError:
                iS = -1
            sig = hash(txt)
            if iS >= 0 and sig != last_sig:
                last_sig = sig
                ymd = int(cur.strftime("%Y%m%d"))
                for x in rows[1:]:
                    if len(x) <= iP or x[iSer].strip() != "EQ":
                        continue
                    try:
                        c, pc = float(x[iC]), float(x[iP])
                    except Exception:
                        continue
                    if pc <= 0 or ca_factor(c / pc) == 1.0:
                        continue
                    sym = x[iS].strip()
                    if ymd in OFFF.get(sym, set()):
                        continue  # already an official split/bonus
                    cands.append((ymd, sym, round((c / pc - 1) * 100, 1)))
    time.sleep(0.25)
    cur += datetime.timedelta(days=1)

# a split-ratio move with NO announcement = crash -> record
crashes = defaultdict(set)
skipped = []
for ymd, sym, mv in cands:
    if announced(sym, ymd):
        skipped.append((ymd, sym, mv))  # real CA -> leave adjusted
    else:
        crashes[sym].add(ymd)

try:
    existing = json.load(open(PC))
except Exception:
    existing = {}
added = 0
for sym, ds in crashes.items():
    cur_list = existing.setdefault(sym, [])
    for ymd in sorted(ds):
        if ymd not in cur_list:
            cur_list.append(ymd)
            added += 1
    cur_list.sort()
json.dump(existing, open(PC, "w"), indent=0, sort_keys=True)
print(
    "scanned %dd | %d split-ratio moves | %d real-CA (kept adjusted) | %d crashes | appended %d new -> phantom_crashes.json"
    % (LOOKBACK, len(cands), len(skipped), sum(len(v) for v in crashes.values()), added)
)
for sym in sorted(crashes):
    print("  CRASH  %-13s %s" % (sym, sorted(crashes[sym])))
