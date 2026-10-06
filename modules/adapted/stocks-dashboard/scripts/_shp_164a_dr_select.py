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


"""D2 selection: a company is re-based pre-2016 only when its FIRST old-format XBRL prints Promoter + Public = 100
with a non-promoter-non-public (custodian) block OUTSIDE that 100 (not just an employee-benefit trust)."""
import json
import os
import sys

REPO = "/Users/dhruvan/stocks-dashboard"
sys.path.insert(0, REPO + "/scripts")
import _shp_dii_rowfix as D

S = os.path.dirname(os.path.abspath(__file__))
hist = json.load(open(REPO + "/scripts/shp_history.json"))
syms = [
    s
    for s in hist
    if not s.startswith("_")
    and isinstance(hist[s], dict)
    and any(q <= "2016-03-31" for q in hist[s])
]
out = {}
stat = {}
for s in syms:
    p = D.LISTS + f"/{s}.json"
    if not os.path.exists(p):
        stat[s] = "no list"
        continue
    d = json.load(open(p))
    t = d.get("Table") if isinstance(d, dict) else d
    cands = sorted(
        [
            (D.qe_of(r.get("qtr")), r.get("XbrlFile"))
            for r in (t or [])
            if D.qe_of(r.get("qtr"))
            and r.get("XbrlFile")
            and "2015-06-30" <= D.qe_of(r.get("qtr")) <= "2022-06-30"
        ]
    )
    f = next((c for c in cands if D.find_file(c[1])), None)
    if not f:
        stat[s] = "no cached old-format xbrl"
        continue
    try:
        bd = D.breakdown(open(D.find_file(f[1]), "rb").read())
    except Exception:
        stat[s] = "parse error"
        continue
    A = bd.get("ShareholdingOfPromoterAndPromoterGroupMember") or 0.0
    B = bd.get("PublicShareholdingMember") or 0.0
    C = bd.get("SharesHeldByNonPromoterNonPublicShareholdersMember") or 0.0
    EBT = bd.get("EmployeeBenefitsTrustsMember") or 0.0
    cust = C - EBT
    if abs(A + B - 100) <= 0.15 and cust >= 0.05:
        out[s] = {
            "first_xbrl": f[1],
            "qe": f[0],
            "A": A,
            "B": B,
            "C": C,
            "EBT": EBT,
            "custodian": round(cust, 4),
        }
        stat[s] = "REBASE (custodian outside the 100)"
    else:
        stat[s] = "keep as printed"
json.dump(out, open(S + "/dr_selected.json", "w"), indent=1)
import collections

print(collections.Counter(stat.values()))
print("selected:", len(out), sorted(out)[:60])
