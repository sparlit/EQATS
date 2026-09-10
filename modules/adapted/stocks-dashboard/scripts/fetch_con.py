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
"""FETCH phase for con-gap recovery. For each residual (sym, gap-quarter) that has NO usable cached PDF
(or whose cached PDF is the wrong attachment: standalone/press-release/notes), fetch EVERY attachment of
the BSE result filing that reports that quarter, and keep the one that actually contains a CONSOLIDATED
P&L (revenue-from-ops + profit row + the word 'consolidated', ideally with a stored neighbor present).
Overwrites _vpdf/SYM_QE.pdf and clears the entry from _vp2_read.json so the next vision batch re-reads it.
Resumable + heartbeat. Run:  python -X utf8 fetch_con.py [MAX]
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_vision as BV  # session()
import congap_recover as C  # datebound/fetch/window/qe_from_ann/scrips/conval/prevq/DEFUNCT
import fitz
import vp2_crop as V2  # find_con_pl_page + REV/PLPFT/AUD/SEG regexes

HERE = os.path.dirname(os.path.abspath(__file__))
VPDF = os.path.join(HERE, "_vpdf")
os.makedirs(VPDF, exist_ok=True)
READF = os.path.join(HERE, "_vp2_read.json")
read_done = json.load(open(READF)) if os.path.exists(READF) else {}
rec = json.load(open(os.path.join(HERE, "_congap_recovered.json")))
HB = os.path.join(HERE, "_fetchcon_hb.txt")
LOG = os.path.join(HERE, "_fetchcon_log.json")
MAX = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 60


def is_con_pl(pdf, sym, qe):
    """Return (True, hint) if this PDF has a genuine consolidated P&L page: a page that contains
    'consolidated' + revenue + a profit row, and ideally a stored neighbor value at some unit scale."""
    try:
        doc = fitz.open(stream=pdf, filetype="pdf")
    except Exception:
        return False, "openfail"
    cprev, cyago = C.conval(sym, C.prevq(qe)), C.conval(sym, qe - 10000)
    p = V2.find_con_pl_page(doc, cprev, cyago)
    if p is None:
        return False, "no-con-pl-page"
    t = doc[p].get_text()
    low = t.lower()
    if "consolidated" not in low:
        return False, "page-not-consolidated"
    if not (V2.REV.search(t) and V2.PLPFT.search(t)):
        return False, "no-rev+pft"
    # bonus: a stored neighbor present somewhere on the page = high confidence
    nums = V2._nums_on(t)
    hint = "con-pl"
    for tgt in (cprev, cyago):
        if tgt is None or abs(tgt) < 3:
            continue
        for sc in (1.0, 10.0, 100.0):
            if any(abs(n - tgt * sc) <= abs(tgt * sc) * 0.01 for n in nums):
                return True, "con-pl+neighbor"
    return True, hint


def targets():
    """refetch-flagged (cached PDF is wrong attachment) first, then nopdf residuals; recent+material."""
    rf, nop = [], []
    for k, v in read_done.items():
        if isinstance(v, list) and v[0] is None and "refetch" in (v[1] or ""):
            s, q = k.rsplit("|", 1)
            rf.append((s, int(q)))
    seen = {k for k, v in read_done.items()}
    for k, v in rec.items():
        if v.get("v") is not None:
            continue
        if k in seen:
            continue
        s, q = k.rsplit("|", 1)
        q = int(q)
        if not os.path.exists(os.path.join(VPDF, "%s_%d.pdf" % (s, q))):
            nop.append((s, q))
    # de-dup, material/recent first
    out = []
    for lst in (rf, nop):
        lst.sort(
            key=lambda sq: (
                -sq[1],
                -max(abs(C.conval(sq[0], C.prevq(sq[1])) or 0), abs(C.conval(sq[0], sq[1] - 10000) or 0)),
            )
        )
        out += lst
    return out


def main():
    o = BV.session()
    log = json.load(open(LOG)) if os.path.exists(LOG) else {}
    tg = targets()
    print("FETCH targets: %d (cap %d)" % (len(tg), MAX), flush=True)
    got = 0
    tried = 0
    for sym, qe in tg:
        key = "%s|%d" % (sym, qe)
        if tried >= MAX:
            break
        if log.get(key) in ("got", "no-con"):
            continue
        code = C.scrips.get(sym)
        if not code or sym in C.DEFUNCT:
            log[key] = "nocode"
            continue
        tried += 1
        lo, hi = C.window(qe)
        try:
            fl = [(a, att) for a, att in C.datebound(o, code, lo, hi) if C.qe_from_ann(a) == qe]
        except Exception:
            fl = []
        best = None
        besthint = None
        for _a, att in fl[:6]:
            try:
                pdf = C.fetch(o, att)
            except Exception:
                pdf = None
            time.sleep(1.5)
            if not pdf:
                continue
            ok, hint = is_con_pl(pdf, sym, qe)
            if ok:
                best = pdf
                besthint = hint
                if hint == "con-pl+neighbor":
                    break  # ideal — stop
        if best:
            open(os.path.join(VPDF, "%s_%d.pdf" % (sym, qe)), "wb").write(best)
            # clear any prior skip so the next vision batch re-renders + re-reads it
            if key in read_done:
                del read_done[key]
                json.dump(read_done, open(READF, "w"), indent=1)
            log[key] = "got"
            got += 1
            print(f"  GOT {key} ({besthint})", flush=True)
        else:
            log[key] = "no-con"
        if tried % 5 == 0:
            json.dump(log, open(LOG, "w"))
            open(HB, "w").write(str(int(time.time())))
            print("  ...%d tried, %d consolidated PDFs fetched" % (tried, got), flush=True)
    json.dump(log, open(LOG, "w"))
    open(HB, "w").write(str(int(time.time())))
    print("FETCH DONE. tried %d, fetched %d consolidated PDFs (ready for vision)." % (tried, got), flush=True)


if __name__ == "__main__":
    main()
