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
"""THE YEAR-LATER READER — read a 2018 consolidated quarter out of the FY+1 filing's comparative.

WHY THIS IS THE ROUTE FOR PRE-2019 CONSOLIDATED CELLS, and why it was found last rather than first:

* §84 — BSE no longer serves pre-Oct-2018 attachments. The company's OWN filing for Mar/Jun-2018 is
  a 404 on both AttachHis and AttachLive. There is nothing to fetch and nothing for vision to render.
* §51a — a 2018 annual filing routinely carries CONSOLIDATED ANNUAL ONLY (verified page by page under
  vision on GAIL's Mar-2019 filing: consolidated P&L p10, consolidated segment report p11, both
  FY-only).
* But once consolidated quarterlies became compulsory from FY2020, the FY+1 filing prints the 2018
  quarter as its YEAR-AGO COMPARATIVE — and that filing is post-Oct-2018, so it is fetchable and
  usually text-bearing.

Measured over the whole 2018 residue (`probe_yearlater_2018.py --all-open`): **206 of 511 open
consolidated cells (40%) have a text-bearing consolidated page printing the target date a year
later**, across 129 companies. Mar-2018 has the MOST hits (91) — the quarter that was hardest for
every other route, because its own filing is gone and Moneycontrol's consolidated series starts at
Jun-2018, is the EASIEST here.

★ THE GATE — the page must prove itself before any number is taken from it.
A printed date alone is not enough (§76b: these filings routinely print both bases, and a date
appears in both halves). So the reader requires the SAME PAGE, under the SAME column mapping, to
reproduce a value WE ALREADY STORE:

    for every OTHER dated column on the page, if we store a consolidated revenue for that quarter,
    the column's revenue must match it to <=0.2%.  >=1 match and ZERO mismatches, else REFUSE.

That is exactly the control every one of the 15 hand-read vision cells landed on (UNIONBANK had
five, PFC reproduced both bases, HINDUNILVR's later columns fixed the summation rule). It is
strictly stronger than a PAT anchor here, because it validates the column mapping itself.

★ AND THE FALLBACK SCREEN STILL APPLIES. A value equal to our stored standalone is refused unless
the company never consolidates differently anywhere (see mc_con_fallback_retro_2018.py).

Fill-only, revenue slot only. Ledger: scripts/yearlater_rev_fills_2018.json (tracked).

  python -X utf8 scripts/fill2020_tools/yearlater_reader_2018.py [--limit N] [--apply]
"""
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

import contextlib

import backfill_revop_gaps as BG  # noqa: E402
import fetch_insurers as FI  # noqa: E402
import fitz  # noqa: E402

PROBE = os.path.join(HERE, "_yearlater_probe_2018.json")
REVOP = os.path.join(ROOT, "docs", "sf_revop.json")
REVOP_SCR = os.path.join(SCRIPTS, "revop_fundamentals.json")
FILLS = os.path.join(SCRIPTS, "yearlater_rev_fills_2018.json")
SKIPS = os.path.join(HERE, "_yearlater_skips_2018.json")

TOL = 0.002
DATE_RE = re.compile(r"(\d{2})[./-](\d{2})[./-](\d{4})")
DATE_RE2 = re.compile(r"(\d{1,2})[-\s]([A-Za-z]{3})[-\s,]*(\d{2,4})")
MON = {
    m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
}


def qe_of_token(tok):
    m = DATE_RE.search(tok)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return y * 10000 + mo * 100 + d
    m = DATE_RE2.search(tok)
    if m and m.group(2).title() in MON:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return y * 10000 + MON[m.group(2).title()] * 100 + int(m.group(1))
    return None


def header_columns(page):
    """(x_centre, qe) for every dated column header, from the y-band carrying the most dates."""
    words = page.get_text("words")
    bands = {}
    for x0, y0, x1, _y1, tok, *_ in words:
        qe = qe_of_token(tok)
        if qe and 20140101 < qe < 20301231:
            bands.setdefault(round(y0 / 4), []).append(((x0 + x1) / 2, qe))
    if not bands:
        return []
    best = sorted(max(bands.values(), key=len))
    # ★ §55b: MATCH BY (DATE, OCCURRENCE), NEVER BY DATE ALONE. The SAME date heads both the
    # QUARTER column and the six-months / nine-months / year-to-date column, so a header routinely
    # carries each date twice. Keeping both made the cumulative figure masquerade as the quarter and
    # then fail the control as a "mismatch" — ASHOKA's page mapped 20190930 to BOTH 1,037.76 (the
    # quarter, which matches our store exactly) and 220,589.50 (the half-year), and the second one
    # sank an otherwise perfect read. The LEFTMOST occurrence of a date is the quarter column.
    seen, out = set(), []
    for cx, qe in best:
        if qe in seen:
            continue
        seen.add(qe)
        out.append((cx, qe))
    return out


def _nums(cells):
    out = []
    for cx, _x0, t in sorted(cells, key=lambda z: z[1]):
        v = t.replace(",", "").replace("(", "-").replace(")", "")
        with contextlib.suppress(ValueError):
            out.append((cx, float(v)))
    return out


def row_values(page, pat):
    """(x_centre, value) for the numeric cells of the LAST row whose label matches `pat`.

    ⚠ THE LABEL AND ITS FIGURES OFTEN LAND ON DIFFERENT EXTRACTED LINES. This is §75b's geometry,
    and it was the dominant failure on the first run of this reader — 30 of 39 refusals were
    "revenue row not parsed" on pages that plainly carry the row. Finolex's standalone statement
    extracts as:

        715.76 807.74 713.97 1523.50 1,505.15 3,077.79      <- the figures, on their own line
        I Revenue from Operations                            <- the label, on the next

    So when the label's own band has too few numbers, take the numeric run from the NEAREST
    adjacent band (above or below) that has enough — the label anchors WHICH row, the neighbouring
    band supplies the values."""
    words = page.get_text("words")
    rows = {}
    for x0, y0, x1, _y1, tok, *_ in words:
        rows.setdefault(round(y0 / 3), []).append(((x0 + x1) / 2, x0, tok))
    keys = sorted(rows)
    hit = None
    for idx, k in enumerate(keys):
        line = " ".join(t for _, _, t in sorted(rows[k], key=lambda z: z[1]))
        if not pat.search(line):
            continue
        nums = _nums(rows[k])
        if len(nums) >= 3:
            hit = nums
            continue
        for off in (-1, 1, -2, 2):  # nearest band first, above before below
            j = idx + off
            if 0 <= j < len(keys):
                cand = _nums(rows[keys[j]])
                # the neighbour must be numeric-only — a band carrying its own label is a
                # DIFFERENT row and lifting its figures would be the §75b mis-read, not the cure
                txt = " ".join(t for _, _, t in rows[keys[j]])
                if len(cand) >= 3 and not re.search(r"[A-Za-z]{4,}", txt):
                    hit = cand
                    break
    return hit or []


def main():
    apply_it = "--apply" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    probe = json.load(open(PROBE))
    revop = json.load(open(REVOP))
    fills = json.load(open(FILLS)) if os.path.exists(FILLS) else {}
    skips = json.load(open(SKIPS)) if os.path.exists(SKIPS) else {}
    o = FI.bse_session()

    work = [(k, v) for k, v in sorted(probe.items()) if v.get("hit")]
    if limit:
        work = work[:limit]
    print("cells with a year-later consolidated page: %d" % len(work), flush=True)

    landed = 0
    for i, (key, rec) in enumerate(work, 1):
        sym, qe, _b = key.split("|")
        qe = int(qe)
        cur = (revop.get(sym) or {}).get(str(qe))
        if cur and len(cur) > 1 and cur[1] is not None:
            continue  # fill-only
        h = rec["hit"]
        raw, _ = BG.cached_pdf(o, h["att"])
        if not raw:
            skips[key] = "attachment gone"
            continue
        try:
            page = fitz.open(stream=raw, filetype="pdf")[h["page"]]
        except Exception:
            skips[key] = "page unopenable"
            continue
        cols = header_columns(page)
        if not cols:
            skips[key] = "no dated header columns"
            continue
        vals = row_values(page, BG.ROW_PATS["rev"])
        if not vals:
            skips[key] = "revenue row not parsed"
            continue

        # map each numeric cell to the nearest dated column
        mapped = []
        for cx, v in vals:
            near = min(cols, key=lambda c: abs(c[0] - cx))
            if abs(near[0] - cx) < 60:
                mapped.append((near[1], v))
        got = [v for q, v in mapped if q == qe]
        if not got:
            skips[key] = "target quarter has no cell in the mapped row"
            continue

        # ★ THE GATE: other columns on this page must reproduce values we already store
        ok = bad = 0
        proof = []
        for q, v in mapped:
            if q == qe:
                continue
            st = (revop.get(sym) or {}).get(str(q))
            if not st or len(st) < 2 or st[1] is None:
                continue
            for scale, lab in ((1.0, "crore"), (0.01, "lakh"), (0.1, "million")):
                if abs(v * scale - st[1]) <= max(0.05, TOL * abs(st[1])):
                    ok += 1
                    proof.append("%d: %.2f(%s) == stored revC %.2f" % (q, v * scale, lab, st[1]))
                    break
            else:
                bad += 1
        if ok < 1 or bad:
            skips[key] = "control failed (%d reproduced / %d mismatched)" % (ok, bad)
            continue
        scale = 1.0
        for s, _l in ((1.0, "crore"), (0.01, "lakh"), (0.1, "million")):
            q0, v0 = next(
                (q, v) for q, v in mapped if q != qe and (revop.get(sym) or {}).get(str(q), [None, None])[1] is not None
            )
            st = revop[sym][str(q0)][1]
            if abs(v0 * s - st) <= max(0.05, TOL * abs(st)):
                scale = s
                break
        val = round(got[0] * scale, 2)
        std = cur[0] if cur else None
        if std not in (None, 0) and abs(val - std) <= 0.001 * abs(std):
            others = [
                q
                for q, r in (revop.get(sym) or {}).items()
                if len(r) > 1 and r[0] not in (None, 0) and r[1] is not None and abs(r[1] - r[0]) > 0.01 * abs(r[0])
            ]
            if others:
                skips[key] = (
                    "equals our standalone and this company consolidates differently in "
                    "%d other quarters — fallback shape, refused" % len(others)
                )
                continue
        fills[key] = {
            "revC": val,
            "src": "BSE ann %s p%d (year-later filing)" % (h["ann"], h["page"]),
            "gate": "same-page control: " + " | ".join(proof[:3]),
            "scale": {1.0: "crore", 0.01: "lakh", 0.1: "million"}[scale],
            "route": "year-later comparative (§84/§51a)",
        }
        landed += 1
        print("  %-24s revC %12.2f  (%s)  %s" % (key, val, fills[key]["scale"], proof[0][:60]), flush=True)
        if i % 25 == 0:
            print("  [%d/%d] landed %d" % (i, len(work), landed), flush=True)

    json.dump(fills, open(FILLS, "w"), indent=1, sort_keys=True)
    json.dump(skips, open(SKIPS, "w"), indent=1, sort_keys=True)
    print("\nREAD %d cells (%d ledgered)" % (landed, len(fills)))
    if not apply_it:
        print("(dry run — ledger written, data untouched. Re-run with --apply)")
        return
    for path in (REVOP, REVOP_SCR):
        d = json.load(open(path))
        n = 0
        for key, c in fills.items():
            sym, qe, _b = key.split("|")
            row = d.setdefault(sym, {}).get(qe) or [None] * 6 + [0, None, None]
            while len(row) < 9:
                row.append(None)
            if row[1] is None:
                row[1] = c["revC"]
                n += 1
            d[sym][qe] = row
        json.dump(d, open(path, "w"), separators=(",", ":"))
        print("APPLIED %d cells to %s" % (n, os.path.basename(path)))


if __name__ == "__main__":
    main()
