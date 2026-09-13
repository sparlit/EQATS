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
"""Deepen docs/bse_fundamentals.json toward 2020 for BSE-only names.

WHY A SEPARATE PASS
  fetch_bse_fund.py reads only a scrip's LAST 3 result filings (recent quarters), its `done` ledger
  is per-scrip (a name that got recent quarters is never revisited), and its vision fallback is
  HARDCODED to 2025-26 quarter-ends — so historical quarters never land. This walks a scrip's OLDER
  result filings (down to --floor, default 2020-01-01) and OCRs the printed quarter with the SAME
  machinery (fetch_bse_fund.page_boxes / parse_pl / qe_from_text), merging fill-only into the same
  store. It never overwrites an existing quarter and never touches fetch_bse_fund's ledger.

CONVERGENT + RESUMABLE
  Own ledger scripts/_bse_fund_hist.json: {code: {"oldest": QE_int, "fails": n, "done": bool}}. Each
  run, per scrip, fetches result filings in [floor, oldest-stored) NEWEST-FIRST and reads up to
  --max-filings of them, so the stored history walks a chunk deeper each run and later runs continue
  below it. A scrip is done when it reaches the floor, runs out of older filings, or resists parsing.
  Only scrips that ALREADY have some data are deepened (the user-visible set), biggest-mcap-first.
  OCR is slow (~1 min/filing), so this is a multi-run grind — bounded by --budget and --max-minutes.

Run: python -X utf8 scripts/backfill_bse_fund_history.py [--budget N] [--max-minutes M]
     [--max-filings K] [--floor YYYYMMDD] [--scrips code,...] [--min-mcap CR]
"""
import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse_fetch as B
import fetch_bse_fund as bf
import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "_bse_fund_hist.json")
MAX_FAIL = 3
WIN_DAYS = 360  # BSE AnnSubCategoryGetData returns EMPTY for windows wider than ~1 year
# strCat=Result narrows to the results category; among those, a P&L filing is usually a Reg-33 /
# board-outcome / (un)audited-results headline — score those first so OCR spends its budget on the
# likely P&L docs (the identity+quarter+PAT gate still rejects anything that isn't one).
ANN_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=Result"
    "&strPrevDate=%s&strToDate=%s&strScrip=%s&strSearch=P&strType=C&subcategory=-1"
)
RESULT_STRONG = re.compile(
    r"financial result|reg(ulation)?\.?\s*33|33\s*\(3\)|outcome of (the )?board"
    r"|unaudited|audited.*result|standalone|consolidated",
    re.IGNORECASE,
)


def _daysdiff(ann_i, qe_i):
    """Calendar days from quarter-end qe_i to announce date ann_i (both YYYYMMDD ints)."""
    a = datetime.date(ann_i // 10000, ann_i // 100 % 100, ann_i % 100)
    q = datetime.date(qe_i // 10000, qe_i // 100 % 100, qe_i % 100)
    return (a - q).days


def result_filings(op, code, from_ymd, to_ymd):
    """Result-category filings (with attachment) in a <=1yr [from,to], best-P&L-candidate first."""
    out, page = [], 1
    while page <= 20:
        try:
            tab = json.loads(B.get(op, ANN_URL % (page, from_ymd, to_ymd, code))).get("Table", []) or []
        except Exception:
            break
        if not tab:
            break
        for r in tab:
            hd = str(r.get("HEADLINE") or "")
            att = r.get("ATTACHMENTNAME")
            if att:
                out.append((str(r.get("NEWS_DT") or "")[:10], att, hd, 0 if RESULT_STRONG.search(hd) else 1))
        if len(tab) < 50:
            break
        page += 1
        time.sleep(0.12)
    out.sort(key=lambda x: (x[3], -(int(x[0].replace("-", "")) if x[0] else 0)))  # strong+newest first
    return out


UNIT_CR = {"crore": 1.0, "lakh": 0.01, "million": 0.1, "thousand": 1e-5, "absolute": 1e-7}


def render_pl_pngs(doc, max_pages=4):
    """PNGs of the P&L-bearing pages: text-hint pages when a text layer exists, else the first pages
    (a scanned Reg-33 results PDF has no text and prints the P&L near the front)."""
    import bse_render

    pngs, saw_text = [], False
    for pi in range(min(len(doc), 12)):
        txt = doc[pi].get_text()
        if txt.strip():
            saw_text = True
            if not bse_render.PL_HINT.search(txt):
                continue
        pngs.append(doc[pi].get_pixmap(dpi=170).tobytes("png"))
        if len(pngs) >= max_pages:
            break
    if not pngs and not saw_text:  # fully scanned → the first pages
        for pi in range(min(len(doc), max_pages)):
            pngs.append(doc[pi].get_pixmap(dpi=170).tobytes("png"))
    return pngs


def read_filing(op, att, name, deadline, floor, oldest, today_i):
    """Return [(qe, rev_cr, pat_cr, basis), ...] for QUARTER columns in [floor, oldest). A cheap OCR
    pre-read fills the current quarter for free; the vision reader then reads ALL columns (comparatives)
    — the real reach on scanned microcaps — one filing yielding several quarters. Values → ₹ crore."""
    raw = bf.fetch_pdf(op, att)
    if not raw:
        return []
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception:
        return []
    out = {}
    # free OCR pre-read: the printed (current) quarter only
    toks = [w for w in re.split(r"[^A-Za-z]+", name.upper()) if len(w) >= 4][:2]
    qe = 0
    rev = pat = None
    unit = None
    ident = False
    basis = "S"
    for pi in range(min(len(doc), 6)):
        if deadline and time.time() > deadline:
            break
        boxes = bf.page_boxes(doc[pi])
        blob = " ".join(b["t"] for b in boxes)
        up = blob.upper()
        if not ident and (any(tk in up for tk in toks) if toks else True):
            ident = True
        if "CONSOL" in up:
            basis = "C"
        if not qe:
            qe = bf.qe_from_text(blob)
        if rev is None or pat is None:
            r2, p2, u2 = bf.parse_pl(boxes)
            rev = rev if rev is not None else r2
            pat = pat if pat is not None else p2
            unit = unit or u2
        if ident and qe and pat is not None:
            break
    if ident and qe and unit and pat is not None and floor <= qe < oldest and qe <= today_i:
        out[qe] = (qe, round(rev * unit, 2) if rev is not None else None, round(pat * unit, 2), basis)
    # vision: read every period column (Claude in the cloud routine; no-op without a key)
    if not (deadline and time.time() > deadline):
        try:
            import bse_vision_api

            pngs = render_pl_pngs(doc)
            v = bse_vision_api.vision_extract_periods(name, pngs) if pngs else None
            if v and v.get("ok"):
                f = UNIT_CR.get(v.get("unit"))
                vb = v.get("basis", "S")
                for p in v.get("periods", []):
                    if p.get("kind") != "Q" or f is None or p.get("pat") is None:
                        continue
                    e = (p.get("end") or "").replace("-", "")
                    if not (e.isdigit() and len(e) == 8):
                        continue
                    qei = int(e)
                    if not (floor <= qei < oldest and qei <= today_i):
                        continue
                    if qei in out and out[qei][3] == vb:  # OCR already got this exact basis
                        continue
                    out[qei] = (
                        qei,
                        round(p["rev"] * f, 2) if p.get("rev") is not None else None,
                        round(p["pat"] * f, 2),
                        vb,
                    )
        except Exception as ex:
            print("    vision err:", str(ex)[:60])
    return list(out.values())


def main():
    def argv(flag, cast, default):
        return cast(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else default

    budget = argv("--budget", int, 40)
    max_min = argv("--max-minutes", float, 60.0)
    max_filings = argv("--max-filings", int, 3)  # vision reads a filing's comparatives too
    floor = argv("--floor", int, 20200101)
    min_mcap = argv("--min-mcap", float, 0.0)
    only = set(sys.argv[sys.argv.index("--scrips") + 1].split(",")) if "--scrips" in sys.argv else None
    today_i = int(datetime.date.today().strftime("%Y%m%d"))
    t_start = time.time()

    univ = json.load(open(bf.UNIV, encoding="utf-8"))["rows"]
    univ.sort(key=lambda r: r[6] or 0, reverse=True)  # biggest mcap first
    data = json.loads(open(bf.OUT, encoding="utf-8").read()) if os.path.exists(bf.OUT) else {"px": {}}
    hist = json.load(open(HIST)) if os.path.exists(HIST) else {}
    op = B.session()
    time.sleep(1)

    spent = added_total = 0
    for r in univ:
        code, tkr, name, _isin, _grp, _fv, mc, _sec = r
        code = str(code)
        if only is not None:
            if code not in only and tkr not in only:
                continue
        else:
            cur = data["px"].get(code) or {}
            if not cur:  # only deepen names that HAVE data
                continue
            if (mc or 0) < min_mcap:
                continue
            h = hist.get(code) or {}
            if h.get("done"):
                continue
        if spent >= budget or (time.time() - t_start) / 60 >= max_min:
            break
        spent += 1
        cur = data["px"].get(code) or {}
        stored = sorted(int(q) for q in cur if str(q).isdigit() and floor <= int(q) <= today_i)
        oldest = stored[0] if stored else today_i
        if oldest <= floor:
            hist[code] = {"oldest": oldest, "fails": 0, "done": True}
            continue
        od = datetime.date(oldest // 10000, oldest // 100 % 100, oldest % 100)
        to_ymd = (od - datetime.timedelta(days=1)).strftime("%Y%m%d")
        from_d = max(
            datetime.date(floor // 10000, floor // 100 % 100, floor % 100), od - datetime.timedelta(days=WIN_DAYS)
        )
        from_ymd = from_d.strftime("%Y%m%d")
        deadline = time.time() + 150
        try:
            filings = result_filings(op, code, from_ymd, to_ymd)
        except Exception as ex:
            print(f"  {code} {tkr} ANN ERR {str(ex)[:50]}")
            filings = []
        added = 0
        newoldest = oldest
        for annd, att, _hd, _sc in filings[:max_filings]:
            if time.time() > deadline:
                break
            try:
                recs = read_filing(op, att, name, deadline, floor, oldest, today_i)
            except Exception:
                recs = []
            annd_i = int(annd.replace("-", "")) if annd and annd.replace("-", "").isdigit() else 0
            for qe, rev, pat, basis in recs:
                if str(qe) in cur:  # fill-only
                    continue
                # attribute the filing's announce date only to ITS OWN quarter (~<=120d after qe);
                # comparative columns were announced ~a year earlier → ann=0 (unknown, honest)
                ann = annd_i if (annd_i and 0 <= _daysdiff(annd_i, qe) <= 120) else 0
                rec = {"pat": pat, "ann": ann, "basis": basis, "src": "hist"}
                if rev is not None:
                    rec["rev"] = rev
                cur[str(qe)] = rec
                added += 1
                newoldest = min(newoldest, qe)
        data["px"][code] = cur
        added_total += added
        fails = (hist.get(code) or {}).get("fails", 0)
        from_i = int(from_ymd)
        if added:
            fails = 0
        else:
            newoldest = min(newoldest, from_i)  # nothing here → step past this window next run
            fails += 1
        done = newoldest <= floor + 300 or from_i <= floor or fails >= MAX_FAIL
        hist[code] = {"oldest": newoldest, "fails": fails, "done": bool(done)}
        print("  %s %-12s oldest %s→%s  +%d qtrs%s" % (code, tkr, oldest, newoldest, added, "  DONE" if done else ""))
        if spent % 8 == 0:
            ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
            data["updated"] = ist.strftime("%Y-%m-%d %H:%M IST")
            json.dump(data, open(bf.OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
            json.dump(hist, open(HIST, "w"))
            time.sleep(0.2)

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    data["updated"] = ist.strftime("%Y-%m-%d %H:%M IST")
    json.dump(data, open(bf.OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(hist, open(HIST, "w"))
    print("WROTE %s: %d scrips this run, +%d historical quarters" % (os.path.normpath(bf.OUT), spent, added_total))


if __name__ == "__main__":
    main()
