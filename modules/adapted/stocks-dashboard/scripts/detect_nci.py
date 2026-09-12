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
"""Detect which owners-conversion-ABSENT Nifty500 stocks have MATERIAL NCI (owners != total),
so only those need owners conversion (no-NCI stocks already have con = owners = total).
For each absent stock, fetch one recent (2023-2024) consolidated results PDF and compare the
'profit for the period' (total) vs 'attributable to owners' rows. Writes _nci_detect.json:
  {sym: {"total":x, "owners":y, "nci_pct":z, "material":bool}}  (or {"note":"no-data"})
Resumable. Run: python -X utf8 detect_nci.py
"""
import datetime
import json
import os
import re
import time
from collections import defaultdict

import bse_vision as V
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(os.path.dirname(HERE), "docs", "sf_fundamentals.json")))
ro = json.load(open(os.path.join(HERE, "_reattr_owners.json")))
scrips = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
OUTF = os.path.join(HERE, "_nci_detect.json")
NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
OWN = re.compile(r"(owners|equity ?holders) of the (parent|company|holding)", re.IGNORECASE)
PFT = re.compile(r"(net\s+)?profit\s*/?\s*\(?\s*loss\)?\s*(after tax\s*)?(for|of)\s*the\s*(period|year)", re.IGNORECASE)
NCIL = re.compile(r"non[- ]?controlling interest|minority interest", re.IGNORECASE)

covered = {k.split("|")[0] for k in ro}
idx = json.load(open(os.path.join(HERE, "indices_history.json")))["Nifty 500"]
M = set()
for x in idx:
    M.update(x["symbols"])
absent = sorted(s for s in M if data.get(s) and any(r[3] is not None for r in data[s]) and s not in covered)

EXTRA = {"GSPL": 532702, "PEL": 500302}


def code(s):
    return scrips.get(s) or EXTRA.get(s)


def tv(w):
    w = w.replace(",", "").replace("(", "-").replace(")", "")
    try:
        return float(w)
    except Exception:
        return None


o = V.session()


def datebound(c, lo, hi):
    out = []
    for pg in range(1, 3):
        u = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1"
            "&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=%s&strType=C" % (pg, lo, c, hi)
        )
        try:
            rows = json.loads(V.get(o, u)).get("Table", [])
        except Exception:
            break
        for r in rows:
            if V.is_result(r) and r.get("ATTACHMENTNAME"):
                a = re.sub(r"[^0-9]", "", (r.get("NEWS_DT") or ""))[:8]
                out.append((int(a) if a else 0, r["ATTACHMENTNAME"]))
        if len(rows) < 50:
            break
    return out


def fetch(att):
    for base in ("AttachHis", "AttachLive"):
        try:
            d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if d[:4] == b"%PDF":
                return d
        except Exception:
            pass
    return None


def analyze(pdf):
    """Return (total, owners, has_nci_line) from the consolidated P&L, else None."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    if sum(len(doc[p].get_text().strip()) for p in range(min(len(doc), 3))) < 200:
        return None
    con = False
    total = owners = None
    nci_line = False
    for p in range(min(len(doc), 24)):
        low = doc[p].get_text().lower()
        if "consolidated" in low:
            con = True
        elif re.search(r"standalone\s+(statement|financial|results)", low) and "consolidated" not in low:
            con = False
        if not con:
            continue
        if NCIL.search(low):
            nci_line = True
        rows = defaultdict(list)
        for w in doc[p].get_text("words"):
            rows[round(w[1] / 3) * 3].append((w[0], w[4]))
        for y in sorted(rows):
            cells = sorted(rows[y])
            lab = " ".join(w for _, w in cells if not NUM.match(w.replace(",", "")))
            l = lab.lower()
            if "before" in l or "comprehensive" in l:
                continue
            nums = [tv(w) for _, w in cells if NUM.match(w.replace(",", ""))]
            nums = [v for v in nums if v is not None]
            if not nums:
                continue
            if OWN.search(l) and owners is None:
                owners = nums[0]
            elif PFT.search(l) and total is None:
                total = nums[0]
    return (total, owners, nci_line)


def main():
    out = json.load(open(OUTF)) if os.path.exists(OUTF) else {}
    todo = [s for s in absent if s not in out]
    print("absent:%d  done:%d  todo:%d" % (len(absent), len(out), len(todo)), flush=True)
    for i, s in enumerate(todo):
        c = code(s)
        if not c:
            out[s] = {"note": "no-bse-code"}
            continue
        if i and i % 10 == 0:
            time.sleep(2)
        fl = datebound(c, "20231015", "20240515")  # FY24 quarters (reliable, post-fix era)
        if not fl:
            out[s] = {"note": "no-recent-results"}
            print("  %-12s no-results" % s, flush=True)
            json.dump(out, open(OUTF, "w"))
            continue
        res = None
        for _ann, att in sorted(fl, reverse=True)[:2]:
            pdf = fetch(att)
            if not pdf:
                continue
            r = analyze(pdf)
            if r and (r[0] is not None or r[1] is not None):
                res = r
                break
        if not res:
            out[s] = {"note": "unparsed"}
            print("  %-12s unparsed" % s, flush=True)
            json.dump(out, open(OUTF, "w"))
            continue
        total, owners, nciln = res
        if total is not None and owners is not None and abs(total) > 1:
            pct = round((total - owners) / abs(total) * 100, 1)
            mat = abs(pct) >= 3 and abs(total - owners) >= 3
            out[s] = {"total": total, "owners": owners, "nci_pct": pct, "material": mat}
            print(
                "  %-12s total=%s owners=%s nci=%.1f%% %s" % (s, total, owners, pct, "MATERIAL" if mat else ""),
                flush=True,
            )
        else:
            out[s] = {"total": total, "owners": owners, "nci_line": nciln, "note": "one-row-only"}
            print("  %-12s partial (total=%s owners=%s)" % (s, total, owners), flush=True)
        json.dump(out, open(OUTF, "w"))
    json.dump(out, open(OUTF, "w"))
    mats = [s for s, v in out.items() if isinstance(v, dict) and v.get("material")]
    print("DONE. material-NCI stocks: %d -> %s" % (len(mats), sorted(mats)), flush=True)


if __name__ == "__main__":
    main()
