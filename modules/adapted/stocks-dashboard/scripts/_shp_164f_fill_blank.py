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


"""Quantmac's 'StockWorld blank' quarters: fetch the quarter's BSE ShareholdingPattern.aspx with the PLAIN client and derive the
cell with fetch_shp_bse_aspx's own parser/gates (cell_of). No impersonation: curl_cffi is shimmed to a plain www-only GET."""
import calendar
import collections
import datetime
import json
import os
import pickle
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
S = os.path.dirname(HERE)
REPO = "/Users/dhruvan/stocks-dashboard"
sys.path.insert(0, S)
from plainget import get as PG


class R:
    def __init__(s, c, b):
        s.status_code = c or 0
        s.content = b
        s.text = b.decode("utf-8", "ignore")


def _get(url, headers=None, impersonate=None, timeout=60, **k):
    if "api.bseindia.com" in url:
        return R(403, b"")
    c, b = PG(url)
    time.sleep(0.8)
    return R(c, b)


m = types.ModuleType("curl_cffi")
m.requests = types.SimpleNamespace(get=_get)
sys.modules["curl_cffi"] = m
sys.modules["curl_cffi.requests"] = m.requests
sys.path.insert(0, REPO + "/scripts")
import fetch_shp_bse_aspx as A

os.environ["SHP_PATH"] = S + "/shp_engine_live_164d.json"
import importlib.util

spec = importlib.util.spec_from_file_location("lv", S + "/ourfii.py")
LV = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LV)
Rp = pickle.load(open(S + "/qm_reply2.pkl", "rb"))


def D(x):
    return x.year * 10000 + x.month * 100 + x.day if isinstance(x, datetime.datetime) else None


master = json.load(open(S + "/bse_master_all.json"))
byid = {
    str(r.get("scrip_id") or "").upper(): int(r["SCRIP_CD"]) for r in master if r.get("scrip_id")
}
bs = json.load(open(REPO + "/scripts/bse_scrips.json"))
byid2 = dict(bs.get("by_id") or {})
hist = json.load(open(REPO + "/scripts/shp_history.json"))


def qe_for(m):
    best = None
    for y in range(m // 10000 - 2, m // 10000 + 1):
        for mo in (3, 6, 9, 12):
            qe = y * 10000 + mo * 100 + calendar.monthrange(y, mo)[1]
            d = datetime.date(y, mo, calendar.monthrange(y, mo)[1]) + datetime.timedelta(days=28)
            if d.year * 10000 + d.month * 100 + d.day <= m and (best is None or qe > best):
                best = qe
    return best


want = {}
for r in Rp["StockWorld blank"]["rows"]:
    m = D(r[0])
    s = r[1]
    qq = D(r[3]) or qe_for(m)
    k = LV.okey(s) or s
    want[(k, qq)] = (s, r[2], r[6])
front = []
unres = []
for (k, qq), (s, qv, src) in sorted(want.items()):
    qe = "%d-%02d-%02d" % (qq // 10000, qq // 100 % 100, qq % 100)
    if qe in (hist.get(k) or {}):
        continue
    code = byid.get(k) or byid2.get(k) or byid.get(s) or byid2.get(s)
    if not code or qe > "2016-03-31":
        unres.append(
            (k, qe, qv, str(src)[:40], "no code" if not code else "XBRL-era (not a page quarter)")
        )
        continue
    front.append(
        {
            "sym": k,
            "qe": qe,
            "code": int(code),
            "qtrid": A.qtrid_of(qe),
            "bname": "",
            "lname": "",
            "qm": qv,
        }
    )
print("page quarters to fetch:", len(front))
print("not by this route:", unres)
out = {}
st = collections.Counter()
for fr in front:
    s_, cell, det = A.cell_of(fr, HERE, None)
    st[s_] += 1
    print(
        "  %-11s %s %-8s QM %s | %s"
        % (fr["sym"], fr["qe"], s_, fr["qm"], (cell[:3] if cell else det)),
        flush=True,
    )
    if s_ == "ok":
        out.setdefault(fr["sym"], {})[fr["qe"]] = cell
json.dump(out, open(HERE + "/fill28_cells.json", "w"), indent=1)
print(dict(st))
