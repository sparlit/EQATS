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
"""ROW-IDENTITY PROOF — the arbiter that outranks both x_sym and holder counts.

For a symbol whose filings park the foreign block on an unlabelled 'Any Others (Specify)'
institutions row, find ANY quarter where BSE's render prints that row AND shp_history holds
an INDEPENDENTLY SOURCED fii for the same quarter (Wayback-MC 2010-2015, the §22f seam
derivation, or a later itemised XBRL). If the two agree to <=0.15pp, that row IS the
company's foreign block, measured — and every quarter of the run takes fii = o_other WHOLE.

If instead the render's Any-Others matches the stored DII-side figure, the row is domestic
and the stored zero stands. Neither -> HOLD.

This is what the holder-count test was a proxy for, and it disagreed with it: SUPREMEIND
Dec-15 renders Any-Others 20.74 == the stored (Wayback-derived) fii 20.74 to the cent.
"""
import json
import os
import sys
import time

SP = os.path.dirname(os.path.abspath(__file__))
HERE = os.environ.get("ZFII_WORKDIR") or SP
sys.path.insert(0, SP)
import contextlib
import re  # noqa: E402

from fetch_shp_bse_aspx import _cells, fetch_page, qtrid_of  # noqa: E402

ASPXDIR = os.path.join(HERE, "aspx")
os.makedirs(os.path.join(ASPXDIR, "cache"), exist_ok=True)


def block_rows(code, qe):
    """-> {row label: (holders, shares, pct)} for the (B)(1) PUBLIC institutions block.
    The holder/share columns are the whole point: they say what the percentages cannot."""
    html, _ = fetch_page(ASPXDIR, code, qtrid_of(qe), "New")
    if not html:
        return None
    cs = _cells(html)
    bi = next((i for i, c in enumerate(cs) if re.search(r"\(B\)\s*Public Shareholding", c, re.IGNORECASE)), None)
    if bi is None:
        return None
    lo = next(
        (i for i in range(bi, len(cs)) if re.search(r"^\(1\)\s*Institutions?$|^Institutions$", cs[i], re.IGNORECASE)),
        bi,
    )
    hi = next(
        (j for j in range(lo + 1, min(lo + 200, len(cs))) if re.fullmatch(r"Sub\s*Total", cs[j], re.IGNORECASE)),
        min(lo + 200, len(cs)),
    )
    out, i = {}, lo
    while i <= hi:
        c = cs[i]
        if re.fullmatch(r"[\d,]+(?:\.\d+)?|-", c):
            i += 1
            continue
        nums, j = [], i + 1
        while j < len(cs) and re.fullmatch(r"[\d,]+(?:\.\d+)?|-", cs[j]):
            nums.append(cs[j].replace(",", ""))
            j += 1
        if len(nums) >= 5:
            with contextlib.suppress(ValueError):
                out[c.strip()] = (int(float(nums[0])), int(float(nums[1])), float(nums[3]))
        i = j if nums else i + 1
    return out or None


def pick(rows, *pats):
    """The LARGEST matching row. This layout prints several foreign rows and all but one are
    0.00 in this era (the block lands on whichever survives — usually QFI), so a first-match
    pick returns the empty row and reads as 'no FPI'. That bug produced a whole wrong pass."""
    best = None
    for lab, v in (rows or {}).items():
        for p in pats:
            if re.search(p, lab, re.IGNORECASE):
                if best is None or v[2] > best[2]:
                    best = v
                break
    return best


def adjq(qe, step):
    y, m = int(qe[:4]), int(qe[5:7])
    m += 3 * step
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return "%04d-%02d-%s" % (y, m, {3: "31", 6: "30", 9: "30", 12: "31"}[m])


TOL = 0.15
raw = json.load(open(os.path.join(HERE, "adjudication_raw.json")))
fin = json.load(open(os.path.join(HERE, "adjudication_final.json")))
holder = json.load(open(os.path.join(HERE, "holder_arbitration.json")))
# The reference history must be the PRE-heal one: a proof quarter has to carry a value this
# campaign did not write, or the test cites itself. Point ZFII_BASE_HIST at a snapshot taken
# before the heal; the checked-in history is only correct here on a first run.
before = json.load(open(os.environ.get("ZFII_BASE_HIST") or os.path.join(SP, "shp_history.json"), encoding="utf-8"))

# the cells whose split is in dispute: every x_sym-dependent heal + every holder HOLD
disputed = sorted(set(holder))
syms = sorted({k.split("|")[0] for k in disputed})
print("row-identity proof for %d symbols / %d disputed cells\n" % (len(syms), len(disputed)))

proof = {}
for sym in syms:
    qs = sorted(q for k, q in (kk.split("|") for kk in disputed) if k == sym)
    code = raw[f"{sym}|{qs[0]}"]["code"]
    stored = before.get(sym) or {}
    # probe quarters: the run's own neighbourhood, oldest run cell -4 .. newest +4
    probes = []
    for st in range(-4, 5):
        probes.append(adjq(qs[0], st))
        probes.append(adjq(qs[-1], st))
    probes = sorted({p for p in probes if p >= "2014-06-30"})
    hits, anti, other_regime = [], [], []
    for pq in probes:
        cell = stored.get(pq)
        if not cell or cell[1] is None or cell[1] <= 0.05:
            continue  # need an independently stored NONZERO fii
        if pq in qs:
            continue  # never test against a disputed cell
        rows = block_rows(code, pq)
        time.sleep(0.15)
        if not rows:
            continue
        o = pick(rows, r"^Any Others?")
        f = pick(rows, r"Qualified Foreign|Foreign Portfolio|Foreign Institutional Investors")
        # REGIME GATE: only a quarter rendered the SAME way as the disputed one can speak for
        # it. Once the filer itemises the foreign row, its Any-Others means something else —
        # that is a regime change, not a contradiction.
        if f and (f[2] or 0) > 0.05:
            other_regime.append(
                {"qe": pq, "foreign_row": f[2], "any_other": o[2] if o else None, "stored_fii": cell[1]}
            )
            continue
        if not o:
            continue
        if abs(o[2] - cell[1]) <= TOL:
            hits.append({"qe": pq, "any_other": o[2], "stored_fii": cell[1], "holders": o[0], "stored_sub": cell[5]})
        elif cell[2] is not None and abs(o[2] - cell[2]) <= TOL:
            anti.append({"qe": pq, "any_other": o[2], "stored_dii": cell[2]})
        else:
            anti.append(
                {
                    "qe": pq,
                    "any_other": o[2],
                    "stored_fii": cell[1],
                    "stored_dii": cell[2],
                    "why": "matches neither slot",
                }
            )
    verdict = "FULL" if hits and not anti else ("DOMESTIC" if anti and not hits else "HOLD")
    proof[sym] = {"verdict": verdict, "hits": hits, "anti": anti, "other_regime_quarters": other_regime, "cells": qs}
    print(
        "%-11s %-8s  same-regime proofs=%d anti=%d (itemised-regime qtrs ignored: %d)\n"
        "              %s"
        % (
            sym,
            verdict,
            len(hits),
            len(anti),
            len(other_regime),
            "; ".join(
                "%s any-other %.2f == stored fii %.2f (%d holders)"
                % (h["qe"], h["any_other"], h["stored_fii"], h["holders"])
                for h in hits[:2]
            )
            or "; ".join(str(a) for a in anti[:2])
            or "no same-regime quarter with a stored fii",
        )
    )

json.dump(proof, open(os.path.join(HERE, "row_identity.json"), "w"), indent=1)
print("\n-> row_identity.json")
