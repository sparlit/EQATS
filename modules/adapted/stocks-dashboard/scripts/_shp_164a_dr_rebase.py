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


"""D2: per-company depository-receipt basis. For each company selected by dr_select.py, every stored pre-2016 cell read
on the page's (A+B+C) column is moved onto the (A+B) column the company's own XBRL uses: all five slots x total(A+B+C)/total(A+B),
both totals read from the SAME quarter's BSE ShareholdingPattern.aspx page (share counts). The basis of the stored cell is
decided per cell from the promoter row (or, with no promoter, the public total) printed in both columns."""
import gzip
import json
import os
import re
import sys as _s
import time

_s.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from plainget import get as PG

S = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/dhruvan/stocks-dashboard"
W = "/private/tmp/claude-501/-Users-dhruvan-stocks-dashboard--claude-worktrees-gifted-lumiere-43c0b8/44738ffa-e5c1-4489-a522-d9aa9f8f6570/scratchpad"
sel = json.load(open(S + "/dr_selected.json"))
hist = json.load(open(REPO + "/scripts/shp_history.json"))
master = json.load(open(S + "/bse_master_all.json"))
byid = {m.get("scrip_id"): m.get("SCRIP_CD") for m in master if m.get("scrip_id")}


def code_of(s):
    f = sel[s]["first_xbrl"]
    return int(f.split("_")[0])


def qtrid(q):
    y = int(q[:4])
    m = int(q[5:7])
    return (y - 2001) * 4 + {3: 29, 6: 30, 9: 31, 12: 32}[m]


H = {"Referer": "https://www.bseindia.com/", "Accept": "text/html,application/xhtml+xml"}


def page(c, qi):
    for p in (
        W + "/aspx_pages/%d_%d.html.gz" % (c, qi),
        S + "/pe_work/aspx_pages/%d_%d.html.gz" % (c, qi),
        S + "/aspx_dr/%d_%d.html.gz" % (c, qi),
    ):
        if os.path.exists(p):
            return gzip.open(p, "rt", encoding="utf-8", errors="ignore").read()
    u = (
        "https://www.bseindia.com/corporates/ShareholdingPattern.aspx?scripcd=%d&flag_qtr=1&qtrid=%d.00&Flag=New"
        % (c, qi)
    )
    code, body = PG(u)  # plain, honestly identified client — www host only (no impersonation)
    txt = body.decode("utf-8", "ignore")
    if code == 200 and len(txt) > 3000:
        with gzip.open(S + "/aspx_dr/%d_%d.html.gz" % (c, qi), "wt", encoding="utf-8") as fh:
            fh.write(txt)
        time.sleep(0.8)
        return txt
    return None


NUM = r"\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([\d.]+)"


def parse(txt):
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", txt).replace("&nbsp;", " "))
    m1 = re.search(r"Total \(A\)\+\(B\)" + NUM, t)
    m2 = re.search(r"Total \(A\)\+\(B\)\+\(C\)" + NUM, t)
    mp = re.search(r"Total shareholding of Promoter and Promoter Group \(A\)" + NUM, t)
    mb = re.search(r"Total Public shareholding \(B\)" + NUM, t)
    mm = re.search(r"Mutual Funds */ *UTI" + NUM, t)
    mf = re.search(r"Foreign Institutional Investors" + NUM, t)
    if not (m1 and m2):
        return None

    def g(m):
        return (int(m.group(2)), float(m.group(4)), float(m.group(5))) if m else None

    return {"ab": g(m1), "abc": g(m2), "prom": g(mp), "pub": g(mb), "mf": g(mm), "fii": g(mf)}


out = {}
stat = {}
for s in sorted(sel):
    c = code_of(s)
    for q in sorted(hist.get(s, {})):
        if q > "2016-03-31":
            continue
        cell = hist[s][q]
        txt = page(c, qtrid(q)) if q >= "2001-03-31" else None
        if not txt:
            stat[s + "|" + q] = "no page"
            continue
        p = parse(txt)
        if not p:
            stat[s + "|" + q] = "page unparsed"
            continue
        ab, abc = p["ab"][0], p["abc"][0]
        if abc <= ab:
            stat[s + "|" + q] = "no custodian shares this quarter"
            continue
        f = abc / ab
        # reference row printed in both columns: promoter when there is one, else the mutual-fund row (least healed slot)
        if p["prom"] and p["prom"][2] > 0.5:
            ref, stored = p["prom"], cell[0]
        elif p["mf"] and p["mf"][2] > 0.3 and cell[3] is not None:
            ref, stored = p["mf"], cell[3]
        else:
            stat[s + "|" + q] = "no reference row"
            continue
        dAB = abs(stored - ref[1])
        dABC = abs(stored - ref[2])
        if dAB + 0.02 < dABC:
            stat[s + "|" + q] = "already on (A+B)"
            continue
        if dABC > 0.06:
            stat[s + "|" + q] = (
                f"stored promoter matches neither column ({stored:.2f} vs {ref[1]:.2f}/{ref[2]:.2f})"
            )
            continue
        new = list(cell)
        for i in range(5):
            if isinstance(new[i], (int, float)):
                new[i] = round(new[i] * f, 4)
        out[s + "|" + q] = {
            "was": cell,
            "cell": new,
            "factor": round(f, 6),
            "ab_shares": ab,
            "abc_shares": abc,
            "src": "bseaspx:%d_%d" % (c, qtrid(q)),
        }
        stat[s + "|" + q] = f"REBASE x{f:.4f}"
import collections

agg = collections.Counter(v if not v.startswith("REBASE") else "REBASE" for v in stat.values())
print(dict(agg))
for k, v in list(stat.items()):
    if v.startswith("stored promoter matches neither"):
        print("  ", k, v)
json.dump(out, open(S + "/dr_rebase_proposals.json", "w"), indent=0)
bys = collections.Counter(k.split("|")[0] for k in out)
print("proposals", len(out), "by symbol", bys.most_common(40))
