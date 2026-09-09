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


#!/usr/bin/env python3
"""Consolidated = standalone where the exchange's index shows NO consolidated result was filed.

SEBI LODR Reg 33 identity, already user-approved 2026-08-06 for this repo
(scripts/con_nofile_identity_fills.json, 378 values). This applies the SAME five gates to the
`basis_absent` residue found by fill_revop_from_xbrl.py — quarters where the con XBRL context
genuinely does not exist because the company filed standalone only.

THE FIVE GATES (verbatim from the approved ledger; all must pass, per cell):
  E1 standalone row present for that exact quarter
  E2 no consolidated row for that quarter          (NSE per-company filing index)
  E3 quarter earlier than the first consolidated filing ever
  E4 stored con PAT already equals std PAT (max(0.05, 0.1%))
  E5 no quarter at-or-before the gap where both rev bases or both PAT bases differ by >1%

E3+E5 are what keep this honest: a company that EVER consolidated separately, or that has ANY
earlier quarter where the two bases diverge, is refused outright — the identity only holds for
filers with nothing to consolidate. Fill-only, idempotent, provenance per cell.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(HERE), "docs")
LIST_CACHE = os.path.join(HERE, "_nse_list_cache")
sys.path.insert(0, HERE)
import build_revop as B

SLOT_STD = {"rev": 0, "op": 2, "ebit": 7}
SLOT_CON = {"rev": 1, "op": 3, "ebit": 8}


def iso_qe(s):
    M = {
        m: i
        for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)
    }
    mm = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})", (s or "").strip())
    return "%04d%02d%02d" % (int(mm.group(3)), M[mm.group(2).title()], int(mm.group(1))) if mm else None


def list_rows(sym):
    p = os.path.join(LIST_CACHE, "{}.json".format(re.sub(r"[^A-Z0-9]", "_", sym.upper())))
    return (json.load(open(p)).get("rows") or []) if os.path.exists(p) else []


def main():
    REVOP = json.load(open(os.path.join(DOCS, "sf_revop.json")))
    RF = json.load(open(os.path.join(HERE, "revop_fundamentals.json")))
    FUND = json.load(open(os.path.join(DOCS, "sf_fundamentals.json")))
    LEDP = os.path.join(HERE, "con_nofile_identity_fills.json")
    LED = json.load(open(LEDP))
    refus = json.load(open(os.path.join(HERE, "_revop_fill_refusals.json")))

    want = {}
    for r in refus:
        if r.get("why", "").startswith("no parseable con") or (
            r.get("basis") == "con" and "no parseable" in r.get("why", "")
        ):
            want.setdefault(r["sym"], set()).add(r["qe"])
    filled = 0
    per = {}
    reasons = {}
    for sym, qes in sorted(want.items()):
        rows = list_rows(sym)
        if not rows:
            reasons.setdefault("no-list", []).append(sym)
            continue
        con_qes, std_qes = set(), set()
        for r in rows:
            q = iso_qe(r.get("toDate"))
            if not q:
                continue
            (con_qes if str(r.get("consolidated", "")).strip().lower() == "consolidated" else std_qes).add(q)
        first_con = min(con_qes) if con_qes else None
        fmap = {str(q[0]): q for q in FUND.get(sym, [])}
        rmap = REVOP.get(sym, {})
        for qe in sorted(qes):
            # E1 / E2 / E3
            if qe not in std_qes:
                reasons.setdefault("E1-no-std-row", []).append(f"{sym}|{qe}")
                continue
            if qe in con_qes:
                reasons.setdefault("E2-con-row-exists", []).append(f"{sym}|{qe}")
                continue
            if first_con is not None and qe >= first_con:
                reasons.setdefault("E3-after-first-con", []).append(f"{sym}|{qe}")
                continue
            # E4 — stored con PAT must already equal std PAT
            q = fmap.get(qe)
            if not q or q[1] is None or q[3] is None:
                reasons.setdefault("E4-no-pat-pair", []).append(f"{sym}|{qe}")
                continue
            if abs(q[3] - q[1]) > max(0.05, abs(q[1]) * 0.001):
                reasons.setdefault("E4-pat-diverges", []).append(f"{sym}|{qe}")
                continue
            # E5 — no earlier quarter where BOTH rev bases or BOTH pat bases differ by >1%
            bad = False
            for oq, c in rmap.items():
                if oq > qe:
                    continue
                if len(c) > 1 and c[0] is not None and c[1] is not None:
                    if abs(c[1] - c[0]) > max(0.01, abs(c[0]) * 0.01):
                        bad = True
                        break
            if not bad:
                for oq, qq in fmap.items():
                    if oq > qe or qq[1] is None or qq[3] is None:
                        continue
                    if abs(qq[3] - qq[1]) > max(0.01, abs(qq[1]) * 0.01):
                        bad = True
                        break
            if bad:
                reasons.setdefault("E5-earlier-divergence", []).append(f"{sym}|{qe}")
                continue
            # all gates pass -> mirror std into con for any null con slot
            row = rmap.get(qe)
            if not row:
                reasons.setdefault("no-revop-row", []).append(f"{sym}|{qe}")
                continue
            wrote = {}
            for f in ("rev", "op", "ebit"):
                si, ci = SLOT_STD[f], SLOT_CON[f]
                if len(row) > ci and row[ci] is None and len(row) > si and row[si] is not None:
                    for store in (REVOP, RF):
                        rr = store.setdefault(sym, {}).get(qe)
                        if rr and len(rr) > ci and rr[ci] is None:
                            rr[ci] = row[si]
                            B.strip_lender_ebit(sym, rr)
                    wrote[f + "C"] = row[si]
                    filled += 1
            if wrote:
                wrote["evidence"] = (
                    "NSE filing index: %d standalone / %d consolidated rows; first consolidated %s "
                    "— no consolidated result filed for this quarter (E1-E5 passed)"
                    % (len(std_qes), len(con_qes), first_con or "never")
                )
                LED.setdefault("fills", {}).setdefault(sym, {})[qe] = wrote
                per.setdefault(sym, []).append(qe)
    LED["last_run_companies"] = len(per)
    LED["last_run_values"] = filled
    LED["values"] = LED.get("values", 0) + filled
    json.dump(REVOP, open(os.path.join(DOCS, "sf_revop.json"), "w"), separators=(",", ":"))
    json.dump(RF, open(os.path.join(HERE, "revop_fundamentals.json"), "w"), separators=(",", ":"))
    json.dump(LED, open(LEDP, "w"), indent=1)
    print("identity fills written: %d cells across %d companies" % (filled, len(per)))
    for k, v in sorted(reasons.items(), key=lambda x: -len(x[1])):
        print("  refused %-24s %d  e.g. %s" % (k, len(v), v[:3]))


if __name__ == "__main__":
    main()
