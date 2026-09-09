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
"""Phase-2 vision cropper for consolidated-gap recovery. For each residual gap (v==null in
_congap_recovered.json) that has a cached _vpdf PDF, render a readable composite: a label bar
(sym, quarter, stored prev/yago for cross-check) + the column-header band + the consolidated
profit/owners rows band, at high DPI. The agent reads these and accepts a value only when the
sibling columns match the stored neighbors (or the visible header date confirms the column).
Renders the next BATCH (recent + material first) not already rendered/read.
Run: python -X utf8 vp2_crop.py [BATCH]
"""
import contextlib
import json
import os
import re
import sys

import cv2
import fitz
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(HERE, "..", "docs", "sf_fundamentals.json")))
rec = json.load(open(os.path.join(HERE, "_congap_recovered.json")))
VP2 = os.path.join(HERE, "_vp2")
os.makedirs(VP2, exist_ok=True)
READF = os.path.join(HERE, "_vp2_read.json")
read_done = json.load(open(READF)) if os.path.exists(READF) else {}
BATCH = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 15


def prevq(qe):
    y, md = qe // 10000, qe % 10000
    return {331: (y - 1) * 10000 + 1231, 630: y * 10000 + 331, 930: y * 10000 + 630, 1231: y * 10000 + 930}[md]


def conval(s, qe):
    for r in data.get(s, []):
        if r[0] == qe:
            return r[3]
    return None


AUD = re.compile(
    r"(independent auditor|auditor.?s report|limited review|review report|we have audited|"
    r"we draw attention|emphasis of matter|our (conclusion|opinion|review)|based on our (review|audit)|"
    r"to the (board|members)|key (standalone )?financial)",
    re.IGNORECASE,
)
PFT = re.compile(r"profit\s*/?\s*\(?\s*loss\)?\s*(after tax|for the (period|quarter|year))", re.IGNORECASE)
DEC = re.compile(r"\d[\d,]*\.\d\d")
SEG = re.compile(
    r"(segment[\s-]*(wise|revenue|result|report|asset|liabilit)|disclosures? in compliance|"
    r"debt[\s-]*equity|ratio\b.*\btimes|coverage ratio|balance sheet|cash flow|"
    r"analytical ratio|solvency ratio|combined ratio|incurred claim ratio|net retention ratio|"
    r"foreign exchange (gain|loss)|ipo proceeds|utilisation of (the )?(net )?(ipo|issue) proceeds|"
    r"statement of assets and liabilit|assets and liabilities)",
    re.IGNORECASE,
)
REV = re.compile(r"(revenue from operations|total income|total revenue|income from operations)", re.IGNORECASE)
BAL = re.compile(r"(equity and liabilities|total equity and liabilit|non-current assets|total assets)", re.IGNORECASE)
PLPFT = re.compile(
    r"(profit\s*/?\s*\(?\s*loss\)?\s*(after tax|for the (period|quarter|year))|"
    r"net profit|profit after tax|profit for the|profit/\(loss\) for)",
    re.IGNORECASE,
)


def find_con_page(doc):
    """Find the CONSOLIDATED P&L STATEMENT page: must have P&L markers (revenue + a profit row),
    NOT a ratios/segment/auditor/balance-sheet page. Falls back to a revenue-bearing page when the
    profit-row label is OCR-garbled."""
    pl = []
    dense = []
    for p in range(min(len(doc), 30)):
        t = doc[p].get_text()
        low = t.lower()
        if "consolidated" not in low or AUD.search(t) or SEG.search(t):
            continue
        nnum = len(DEC.findall(t))
        if nnum < 10:
            continue  # dense numeric table only (skip cover letters)
        has_pl = "profit for the" in low or PFT.search(t)
        has_rev = bool(REV.search(t))
        if has_rev and has_pl:
            pl.append((nnum + 200, p))  # ideal P&L page
        elif has_pl or has_rev:
            pl.append((nnum + 80, p))  # partial markers (one garbled)
        else:
            dense.append((nnum, p))  # dense consolidated table, both labels garbled
    if pl:
        pl.sort(reverse=True)
        return pl[0][1]
    if dense:
        dense.sort(reverse=True)
        return dense[0][1]
    return None


NPAT = re.compile(
    r"(net\s+)?profit\s*/?\s*\(?\s*loss\)?\s*.{0,18}(after tax|for the (period|quarter|year))", re.IGNORECASE
)


def _nums_on(t):
    out = []
    for w in re.findall(r"\(?-?[\d,]+\.\d\d\)?", t):
        v = w.replace(",", "").replace("(", "-").replace(")", "")
        with contextlib.suppress(Exception):
            out.append(float(v))
    return out


def find_pl_page_by_neighbors(doc, cprev, cyago):
    """Verification-driven: the P&L page is the one whose text contains the STORED neighbor values
    (prev and/or yago) at some unit scale (/1,/10,/100). Far more reliable than density heuristics for
    multi-page insurer/large-cap filings. Returns page index or None."""
    tgts = [t for t in (cprev, cyago) if t is not None and abs(t) >= 3]
    if not tgts:
        return None
    best = None
    best_score = 0.0
    for p in range(min(len(doc), 32)):
        t = doc[p].get_text()
        low = t.lower()
        if AUD.search(t) or SEG.search(t):
            continue
        # the P&L page must actually have a profit row (rules out balance-sheet/segment coincidental matches)
        if not (PFT.search(t) or "profit for the" in low or "net profit" in low or "profit after tax" in low):
            continue
        nums = _nums_on(t)
        if len(nums) < 4:
            continue
        score = 0.0
        for tgt in tgts:
            for sc in (1.0, 10.0, 100.0):
                if any(abs(n - tgt * sc) <= abs(tgt * sc) * 0.004 for n in nums):  # 0.4% exact-ish match
                    score += 1.0
                    break
        if score > best_score:
            best_score = score
            best = p
    return best if best_score >= 1.0 else None


def find_con_pl_page(doc, cprev, cyago):
    """STRICT consolidated-P&L finder. The page must be a real P&L: a revenue-from-operations row AND a
    profit/PAT row. Rejects balance-sheet (no revenue), segment/notes/auditor/reconciliation pages, and
    standalone-only pages. Scores by neighbor-value match (strong) + consolidated label + table density.
    This is the PRIMARY finder for multi-page annual filings (the value-only finder kept landing on
    balance-sheet/notes decoys that happen to contain a stored neighbor number)."""
    tgts = [t for t in (cprev, cyago) if t is not None and abs(t) >= 3]
    best = None
    best_score = -1e9
    for p in range(min(len(doc), 34)):
        t = doc[p].get_text()
        low = t.lower()
        if AUD.search(t):
            continue  # skip auditor / limited-review pages
        # POSITIVE gate: a real P&L has BOTH a revenue-from-ops row AND a profit/PAT row. This alone
        # excludes balance-sheet / segment / ratio / notes / cash-flow pages -- so do NOT also reject on
        # SEG (it false-matches P&L pages that merely mention 'segment' in a one-segment note).
        if not (REV.search(t) and PLPFT.search(t)):
            continue
        # TABLE density (SCORE, not a hard gate): a real P&L has many rows with >=3 numbers each (multi-
        # column grid); notes/press-release prose pages mention 'consolidated'/'revenue'/'profit' in
        # sentences but have few such rows. Count any number token (incl small/decimal & whole-lakh).
        rows3 = sum(1 for ln in t.split("\n") if len(re.findall(r"-?\(?[\d,]*\d(?:\.\d+)?\)?", ln)) >= 3)
        is_con = "consolidated" in low
        is_std_only = ("standalone" in low) and not is_con
        nums = _nums_on(t)
        score = min(rows3, 30) / 10.0  # dense numeric TABLE strongly preferred (prose ~0-0.5)
        for tgt in tgts:  # neighbor value present on this page?
            for sc in (1.0, 10.0, 100.0):
                if any(abs(n - tgt * sc) <= abs(tgt * sc) * 0.006 for n in nums):
                    score += 2.5
                    break
        if is_con:
            score += 3.0  # strongly prefer the CONSOLIDATED P&L
        if is_std_only:
            score -= 3.0  # avoid the standalone-only P&L
        if score > best_score:
            best_score = score
            best = p
    return best


def profit_band(pg):
    """y-range covering the net-profit-after-tax row through the owners/NCI attribution rows."""
    H = pg.rect.height
    ys = []
    for b in pg.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = " ".join(s["text"] for s in ln["spans"])
            low = t.lower()
            if len(DEC.findall(t)) < 2:
                continue
            if "before" in low or "comprehensive" in low or "exceptional" in low:
                continue
            if (
                NPAT.search(t)
                or "profit for the" in low
                or "profit/(loss) for" in low
                or "profit /(loss) for" in low
                or "owners of" in low
                or "non-controlling" in low
                or "equity holder" in low
            ):
                ys.append(ln["bbox"][1] / H)
    if ys:
        return max(0.04, min(ys) - 0.05), min(0.97, max(ys) + 0.13)
    return 0.33, 0.86


def render(sym, q, pdfpath, full=False):
    """Render the consolidated P&L table region (header + profit rows) as one image. full=True (REZOOM)
    renders the WHOLE table region [0.08-0.95] at higher DPI so a band-cut or wrong-row can never hide
    the net-profit line. Label bar carries stored neighbors for cross-check."""
    try:
        doc = fitz.open(pdfpath)
    except Exception:
        return None
    cprev, cyago = conval(sym, prevq(q)), conval(sym, q - 10000)
    p = find_con_pl_page(doc, cprev, cyago)  # PRIMARY: strict consolidated-P&L page
    if p is None:
        p = find_pl_page_by_neighbors(doc, cprev, cyago)
    if p is None:
        p = find_con_page(doc)
    if p is None:
        return None
    pg = doc[p]
    H = pg.rect.height
    W = pg.rect.width
    y0, y1 = profit_band(pg)
    DPI = 420 if full else 300
    Wt = 2600 if full else 2200
    # Side-by-side detection: standalone AND consolidated both as headers in the top band -> crop the
    # label strip + the consolidated (right) half only, so the consolidated digits stay large/readable.
    toptext = " ".join(w[4] for w in pg.get_text("words") if w[1] / H < 0.45).lower()
    sbs = "standalone" in toptext and "consolidated" in toptext
    conx = 0.52 if sbs else 0.30

    def piece(x0, x1, a, b):
        pm = pg.get_pixmap(dpi=DPI, clip=fitz.Rect(W * x0, H * a, W * x1, H * b))
        im = np.frombuffer(pm.samples, np.uint8).reshape(pm.height, pm.width, pm.n)
        return cv2.cvtColor(im, cv2.COLOR_RGB2BGR) if pm.n == 3 else cv2.cvtColor(im, cv2.COLOR_RGBA2BGR)

    def band(a, b):
        if sbs:
            L = piece(0.0, 0.30, a, b)
            R = piece(conx, 1.0, a, b)
            h = min(L.shape[0], R.shape[0])
            sep = np.full((h, 14, 3), 200, np.uint8)
            return cv2.hconcat([L[:h], sep, R[:h]])
        return piece(0.0, 1.0, a, b)

    def rw(im):
        return cv2.resize(im, (Wt, int(im.shape[0] * Wt / im.shape[1])))

    try:
        if full:
            body = rw(band(0.08, 0.95))  # whole statement: header + every row, no band-cut risk
            parts = [body]
        else:
            hdr = rw(band(0.10, 0.27))
            prof = rw(band(y0, y1))
            parts = [hdr, np.full((6, Wt, 3), 210, np.uint8), prof]
    except Exception:
        return None
    pq, yq = prevq(q), q - 10000
    bar = np.full((58, Wt, 3), 30, np.uint8)
    cv2.putText(
        bar,
        "%s  Qend=%d   stored prev(%d)=%s  yago(%d)=%s%s"
        % (sym, q, pq, conval(sym, pq), yq, conval(sym, yq), "  [REZOOM full]" if full else ""),
        (10, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
    )
    out = np.vstack([bar, *parts])
    fn = os.path.join(VP2, "%s_%d.png" % (sym, q))
    cv2.imwrite(fn, out)
    return fn


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "rezoom":
        # Re-render ONLY the retry-rezoom-flagged skips (data is in-PDF, finder grabbed a decoy page or
        # the band cut the net-profit row) using the strict consolidated-P&L finder + full-page crop.
        flagged = [
            k for k, v in read_done.items() if isinstance(v, list) and v[0] is None and "retry-rezoom" in (v[1] or "")
        ]
        manifest = []
        for k in sorted(flagged):
            s, q = k.rsplit("|", 1)
            q = int(q)
            pdfp = os.path.join(HERE, "_vpdf", "%s_%d.pdf" % (s, q))
            if not os.path.exists(pdfp):
                print("  no-pdf", k)
                continue
            fn = render(s, q, pdfp, full=True)
            if fn:
                manifest.append(
                    {
                        "sym": s,
                        "qe": q,
                        "prevq": prevq(q),
                        "yagoq": q - 10000,
                        "prev": conval(s, prevq(q)),
                        "yago": conval(s, q - 10000),
                        "img": os.path.basename(fn),
                    }
                )
        json.dump(manifest, open(os.path.join(VP2, "manifest.json"), "w"), indent=1)
        print("REZOOM rendered %d/%d flagged crops:" % (len(manifest), len(flagged)))
        for m in manifest:
            print("  %s_%d.png  prev=%s yago=%s" % (m["sym"], m["qe"], m["prev"], m["yago"]))
        return
    # residuals with cached PDF, not yet vision-read; recent + material first
    cand = []
    for k, v in rec.items():
        if v.get("v") is not None:
            continue
        if k in read_done:
            continue
        s, q = k.rsplit("|", 1)
        q = int(q)
        pdfp = os.path.join(HERE, "_vpdf", "%s_%d.pdf" % (s, q))
        if not os.path.exists(pdfp):
            continue
        mag = max(abs(conval(s, prevq(q)) or 0), abs(conval(s, q - 10000) or 0))
        cand.append((q, mag, s, pdfp))
    cand.sort(key=lambda x: (-x[0], -x[1]))
    manifest = []
    for q, mag, s, pdfp in cand:
        if len(manifest) >= BATCH:
            break
        fn = render(s, q, pdfp)
        if fn:
            manifest.append(
                {
                    "sym": s,
                    "qe": q,
                    "prevq": prevq(q),
                    "yagoq": q - 10000,
                    "prev": conval(s, prevq(q)),
                    "yago": conval(s, q - 10000),
                    "img": os.path.basename(fn),
                }
            )
    json.dump(manifest, open(os.path.join(VP2, "manifest.json"), "w"), indent=1)
    print(
        "rendered %d crops; %d cached residuals remain after this batch"
        % (len(manifest), len(list(cand)) - len(manifest))
    )
    for m in manifest:
        print("  %s_%d.png  prev=%s yago=%s" % (m["sym"], m["qe"], m["prev"], m["yago"]))


if __name__ == "__main__":
    main()
