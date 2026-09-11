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
"""GICRE con+std revenue from its own filing packs — the format-specific reader.

WHY: insurer_con_rev.py refuses every GICRE quarter with "std control failed: filing reads None".
That is the READER, not the document — the text layer is glyph-corrupted in the LABELS
("OPERA TING RES UL TS", "Premium Earned /Net\\", "Profit I tlossl after tax", "/bl Income from
investments") while the FIGURES extract cleanly. Generic label patterns miss; corruption-tolerant
fragments plus geometric column mapping hit (runbook §51b + §55b).

CONVENTION (general insurer, §55): revenue = Premium Earned (Net)
                                          + policyholders' Income from investments (net)
                                          + shareholders' Income from investments [row 18(b)]

PROVEN on Mar-2023 before any write:
  std page p6:  7,65,911 + 1,74,909 + 1,14,812 = 10,55,632 lakh = 10556.32 == stored revS EXACTLY
  con page p21: 7,72,396 + 1,74,889 + 1,18,302 = 10,65,587 lakh = 10655.87
  anchor      : con page "Profit for the year" 2,72,918 lakh = 2729.18 == stored con PAT EXACTLY
  identity    : 2,60,928 (PAT after tax) + 11,990 (associates) = 2,72,918 — the page's own sum
  ratio       : con/std 1.0094, inside GICRE's own stored family 1.0000-1.0497 (n=8)

GATES (all must hold per quarter, else skip WITH a reason):
  G1 the page declares its basis (Consolidated / Standalone) and the target quarter's date heads
     a column — the column is chosen BY PRINTED DATE, never by index (§55b);
  G2 A5 control: the SAME filing's standalone page reproduces our stored revS within 0.5%;
  G3 anchor: the con page's owners-attributable profit == stored con PAT within max(2cr, 3%);
  G4 ratio family: con/std within the company's own stored min..max, padded 1%.

  python -X utf8 scripts/fill2020_tools/gicre_reader.py [--qe YYYYMMDD] [--apply]
"""
import glob
import json
import os
import re
import sys

import fitz

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
PDFCACHE = os.path.join(SCRIPTS, "_ins_pdfcache")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_LED = os.path.join(SCRIPTS, "revop_fundamentals.json")
FUND = os.path.join(ROOT, "docs", "sf_fundamentals.json")
LEDGER = os.path.join(SCRIPTS, "gicre_rev_fills.json")

NUM = re.compile(r"^\(?-?[\d,][\d, ]*\)?$")
# corruption-tolerant row fragments (the OCR/text-layer mangles punctuation, not digits)
R_PREM = re.compile(r"Premium\s*Earned", re.IGNORECASE)
R_PHINV = re.compile(r"^\s*4\s+Income from investments", re.IGNORECASE)
R_SHINV = re.compile(r"Income from investments$|^.b.\s*Income from investments", re.IGNORECASE)
R_PROFIT_YR = re.compile(r"Profit for the", re.IGNORECASE)
R_PAT = re.compile(r"Profit\s*I?\s*.?loss.?\s*after tax", re.IGNORECASE)
R_ASSOC = re.compile(r"Share of Profit in Associate", re.IGNORECASE)
DATEHDR = re.compile(r"\((\d{2})/(\d{2})/(\d{4})\)")


def num(tok):
    t = tok.replace(",", "").replace(" ", "")
    neg = t.startswith("(") or t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def page_rows(pg):
    """[(y, [(x, token)...])] — words clustered into visual rows."""
    rows = {}
    for x0, y0, _x1, _y1, w, *_ in pg.get_text("words"):
        rows.setdefault(round(y0 / 4), []).append((x0, w))
    return [(k, sorted(v)) for k, v in sorted(rows.items())]


def columns_of(pg, qe):
    """x-centres of the dated column headers, and the index of the target quarter's column."""
    want = "%02d/%02d/%04d" % (qe % 100, (qe // 100) % 100, qe // 10000)
    for _y, toks in page_rows(pg):
        line = " ".join(t for _x, t in toks)
        hits = DATEHDR.findall(line)
        if len(hits) >= 3:
            xs = [x for x, t in toks if DATEHDR.search(t)]
            dates = ["{}/{}/{}".format(*h) for h in hits]
            if want in dates and len(xs) == len(dates):
                return xs, dates.index(want)
    return None, None


def value_at(toks, xs, idx):
    """Value under the idx-th dated column, chosen GEOMETRICALLY.

    Two traps this exists to avoid, both seen on GICRE's own pages:
      * the leading SI. No. ("3 Premium Earned ...") is a perfectly good number sitting to the
        LEFT of every data column — positional indexing grabs it and returns 3 instead of
        7,72,396 (first version of this reader returned 0.08 for a 10,655.87 cell);
      * rows print a nil as blank, so the k-th number is not the k-th column.
    So: keep only tokens inside the column band, then snap each to its nearest header centre."""
    left = min(xs) - 40
    # MERGE SPLIT DIGIT GROUPS FIRST. GICRE's text layer tears Indian groupings apart:
    # "Profit for the year 2 72 918 ..." is three tokens, and taking the first returns 2 instead
    # of 2,72,918 (that is how the anchor read 2.72 against a stored 2729.18). Tokens that sit
    # within ~14pt of each other belong to one printed figure, so glue them before snapping.
    frag = [(x, t) for x, t in toks if x >= left and re.match(r"^\(?-?[\d,]+\)?$", t)]
    merged, i = [], 0
    while i < len(frag):
        x0, s = frag[i]
        j = i + 1
        while j < len(frag) and frag[j][0] - frag[j - 1][0] <= 14:
            s += frag[j][1]
            j += 1
        merged.append((x0, s))
        i = j
    nums = [(x, num(s)) for x, s in merged if num(s) is not None]
    if not nums:
        return None
    best = {}
    for x, v in nums:
        j = min(range(len(xs)), key=lambda k: abs(xs[k] - x))
        if j not in best or abs(xs[j] - x) < abs(xs[j] - best[j][0]):
            best[j] = (x, v)
    hit = best.get(idx)
    return hit[1] if hit else None


def read_page(pg, qe):
    xs, idx = columns_of(pg, qe)
    if xs is None:
        return None
    got = {}
    for _y, toks in page_rows(pg):
        line = " ".join(t for _x, t in toks)
        for key, pat in (
            ("prem", R_PREM),
            ("phinv", R_PHINV),
            ("shinv", R_SHINV),
            ("profit_yr", R_PROFIT_YR),
            ("pat", R_PAT),
            ("assoc", R_ASSOC),
        ):
            if pat.search(line) and key not in got:
                v = value_at(toks, xs, idx)
                if v is not None:
                    got[key] = v
    return got or None


def main():
    only_qe = int(sys.argv[sys.argv.index("--qe") + 1]) if "--qe" in sys.argv else None
    apply_it = "--apply" in sys.argv
    revop = json.load(open(REVOP))
    fund = {int(r[0]): (r[1], r[3]) for r in json.load(open(FUND))["GICRE"] if len(r) > 3}
    fam = [v[1] / v[0] for v in revop["GICRE"].values() if v[0] is not None and v[1] is not None and v[0]]
    lo, hi = (min(fam) * 0.99, max(fam) * 1.01) if fam else (0.9, 1.2)

    qes = sorted(
        {int(q) for q, v in revop["GICRE"].items() if (v[1] is None or v[0] is None) and 20200101 <= int(q) <= 20261231}
    )
    if only_qe:
        qes = [only_qe]
    print(f"GICRE open quarters: {qes}\nratio family {lo:.4f}..{hi:.4f}")
    out = {}
    for qe in qes:
        packs = sorted(glob.glob(os.path.join(PDFCACHE, "GICRE_%d_*" % qe)))
        best = None
        for p in packs:
            try:
                doc = fitz.open(p)
            except Exception:
                continue
            con_v = std_v = anchor = None
            for pg in doc:
                t = pg.get_text()
                if not DATEHDR.search(t):
                    continue
                is_con = re.search(r"Statement of Consolidated", t)
                is_std = re.search(r"Statement of Standalone", t)
                if not (is_con or is_std):
                    continue
                g = read_page(pg, qe)
                if not g or "prem" not in g or "phinv" not in g:
                    continue
                rev = (g["prem"] + g["phinv"] + g.get("shinv", 0.0)) / 100.0
                if is_con:
                    con_v = round(rev, 2)
                    anchor = (g.get("profit_yr") or 0) / 100.0 or None
                else:
                    std_v = round(rev, 2)
            # Keep the BEST pack, never merely the last. A quarter caches several attachments and
            # some carry only one basis; overwriting a con+std pack with a con-only one destroyed
            # the A5 control (and paired a good revenue read with another file's anchor).
            # The control must come from the SAME filing, so both bases must land in ONE pdf.
            cand = {"pdf": os.path.basename(p), "con": con_v, "std": std_v, "anchor": anchor}
            score = (con_v is not None) + (std_v is not None) + (anchor is not None)
            if con_v or std_v:
                if best is None or score > best["_score"]:
                    cand["_score"] = score
                    best = cand
                if con_v and std_v and anchor:
                    break
        if not best:
            out[qe] = {"skip": "no dated con/std statement page found in %d packs" % len(packs)}
            print("  %d  SKIP no readable statement page (%d packs)" % (qe, len(packs)))
            continue
        stored_std, _stored_con = revop["GICRE"][str(qe)][0], revop["GICRE"][str(qe)][1]
        _s_pat, c_pat = fund.get(qe, (None, None))
        v = dict(best)
        v["stored_std"], v["stored_con_pat"] = stored_std, c_pat
        # G2 A5 control
        v["ctrl_ok"] = (
            best["std"] is not None
            and stored_std is not None
            and abs(best["std"] - stored_std) <= max(1.0, 0.005 * abs(stored_std))
        )
        # G3 anchor
        v["anchor_ok"] = (
            best["anchor"] is not None
            and c_pat is not None
            and abs(best["anchor"] - c_pat) <= max(2.0, 0.03 * abs(c_pat))
        )
        # G4 ratio
        v["ratio"] = round(best["con"] / stored_std, 4) if (best["con"] and stored_std) else None
        v["ratio_ok"] = v["ratio"] is not None and lo <= v["ratio"] <= hi
        out[qe] = v
        print(
            "  %d  con=%-10s std=%-10s ctrl=%-5s anchor=%-6s(%s vs %s) ratio=%-7s %s"
            % (
                qe,
                best["con"],
                best["std"],
                v["ctrl_ok"],
                v["anchor_ok"],
                best["anchor"],
                c_pat,
                v["ratio"],
                "PASS" if (v["ctrl_ok"] and v["anchor_ok"] and v["ratio_ok"]) else "hold",
            )
        )
    json.dump(out, open("/tmp/gicre_reads.json", "w"), indent=1, default=str)
    if not apply_it:
        print("\n(dry run — /tmp/gicre_reads.json)")
        return
    led = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    n = 0
    for path in (REVOP, REVOP_LED):
        d = json.load(open(path))
        for qe, v in out.items():
            if not isinstance(v, dict) or v.get("skip"):
                continue
            if not (v.get("ctrl_ok") and v.get("anchor_ok") and v.get("ratio_ok")):
                continue
            row = d.get("GICRE", {}).get(str(qe))
            if not row or row[1] is not None or v["con"] is None:
                continue
            while len(row) < 9:
                row.append(None)
            row[1] = v["con"]
            d["GICRE"][str(qe)] = row
            n += 1
            led["GICRE|%d|revC" % qe] = {
                "revC": v["con"],
                "src": "BSE filing pack {}".format(v["pdf"]),
                "evidence": (
                    "GI convention prem+ph-inv+sh-inv; A5 std control {} vs stored {}; "
                    "anchor {} vs stored con PAT {}; ratio {} in family".format(
                        v["std"], v["stored_std"], v["anchor"], v["stored_con_pat"], v["ratio"]
                    )
                ),
                "applied": "2026-08-11 GICRE format reader",
            }
        json.dump(d, open(path, "w"), separators=(",", ":"))
    json.dump(led, open(LEDGER, "w"), indent=1, sort_keys=True)
    print("APPLIED %d cell-values" % n)


if __name__ == "__main__":
    main()
