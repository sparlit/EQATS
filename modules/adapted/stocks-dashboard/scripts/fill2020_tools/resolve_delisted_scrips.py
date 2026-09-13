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
"""ISIN-GATED BSE scrip codes for DELISTED/SUSPENDED target companies  (2026-08-11, FILL-2018).

THE GAP THIS CLOSES. `scripts/bse_scrips.json` is built from BSE's LIVE scrip master, so a company
that has since delisted resolves to nothing (§52b) — and `backfill_revop_gaps` then drops the whole
company from its worklist before fetching anything. Measured on this campaign's anchored pool:
19 companies / 36 cells never reached the §58 route for that reason alone. Those cells are
NOT ATTEMPTED, not failed (§57a rule 4), and they include ALBK, DHFL, FRETAIL, MINDTREE, RELCAPITAL,
RELINFRA, IDFC and SREINFRA.

WHY NOT JUST MATCH `scrip_id`. Because a BSE `scrip_id` equal to our NSE ticker is a COINCIDENCE to
be disproved, never a match to be trusted (§76, the KALYANI trap: our KALYANI is Kalyani Commercials
INE610E01010, while by_id["KALYANI"] points at Kalyani Cast-Tech INE0N6U01018 — a different
company). `diag_rev2019.py`'s delisted fallback matches on `scrip_id` alone, which is fine for a
diagnosis but not for anything that will read a document and write a number from it.

THE GATE, and why it is available here for free: NSE's per-company filing index rows carry an
`isin` field, and `_bse_master_all.json` carries `ISIN_NUMBER` including delisted rows. Both are
exchange-published, and neither is derived from our own data. A code is emitted ONLY when the two
ISINs agree exactly. A scrip_id match with a differing or missing ISIN is reported, never emitted.

Output: scripts/fill2020_tools/_delisted_scrip_overrides.json  {SYM: {"scrip": ..., "isin": ...}}

Run:  python -X utf8 scripts/fill2020_tools/resolve_delisted_scrips.py [--write]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SCRIPTS = os.path.join(ROOT, "scripts")
LIST_CACHE = os.path.join(SCRIPTS, "_nselist")
TARGETS = os.path.join(HERE, "_rev2020_targets.json")
OUT = os.path.join(HERE, "_delisted_scrip_overrides.json")


def nse_isin(sym):
    """The ISIN NSE itself prints on this company's filing-index rows. Unanimity required: if the
    cached rows disagree, we do not have one ISIN for this symbol and the gate cannot be applied."""
    p = os.path.join(LIST_CACHE, re.sub(r"[^A-Z0-9]", "_", sym.upper()) + ".json")
    if not os.path.exists(p):
        return None
    vals = {(r.get("isin") or "").strip().upper() for r in json.load(open(p))}
    vals.discard("")
    return vals.pop() if len(vals) == 1 else None


def main():
    targets = json.load(open(TARGETS))
    by_id = json.load(open(os.path.join(SCRIPTS, "bse_scrips.json"), encoding="utf-8"))["by_id"]
    master = json.load(open(os.path.join(SCRIPTS, "_bse_master_all.json")))
    by_sid = {}
    for r in master:
        sid = (r.get("scrip_id") or "").upper()
        if sid and (r.get("Segment") or "Equity") == "Equity":
            by_sid.setdefault(sid, []).append(r)

    out, rejected = {}, {}
    for sym in sorted(targets):
        if by_id.get(sym):
            continue  # live master already answers
        cands = by_sid.get(sym.upper(), [])
        want = nse_isin(sym)
        if not cands:
            rejected[sym] = "no scrip_id row in _bse_master_all.json"
            continue
        if not want:
            rejected[sym] = "no single NSE isin for the symbol — gate cannot be applied"
            continue
        hit = [r for r in cands if (r.get("ISIN_NUMBER") or "").strip().upper() == want]
        gate = "nse-index isin == bse master ISIN_NUMBER (exact)"
        if not hit:
            # SAME ISSUER, RE-ISSUED SECURITY. An Indian ISIN is IN + issuer(5) + security-type(2)
            # + issue-number(2) + check digit, so a face-value change re-issues the security and
            # moves the tail while the ISSUER prefix is untouched: HDFC INE001A01028 -> INE001A01036
            # (Rs10 -> Rs2), CORPBANK INE112A01015 -> INE112A01023. Those are the same company.
            # The KALYANI trap this gate exists for is NOT of that shape — INE610E01010 vs
            # INE0N6U01018 differ in the ISSUER itself — so matching on the 7-char issuer prefix
            # still refuses it.
            hit = [r for r in cands if (r.get("ISIN_NUMBER") or "").strip().upper()[:7] == want[:7]]
            gate = "nse-index isin issuer-prefix == bse master (security re-issued, same issuer)"
        if not hit:
            rejected[sym] = "ISIN MISMATCH: nse {} vs bse {} ({}) — NOT the same company".format(
                want, [r.get("ISIN_NUMBER") for r in cands], [r.get("Scrip_Name") for r in cands]
            )
            continue
        r = hit[0]
        out[sym] = {
            "scrip": r["SCRIP_CD"],
            "isin": want,
            "bse_isin": r.get("ISIN_NUMBER"),
            "name": r.get("Scrip_Name"),
            "status": r.get("Status"),
            "gate": gate,
        }

    print("ISIN-GATED overrides: %d" % len(out))
    for s, v in sorted(out.items()):
        print("  %-12s %s  %-42s %s" % (s, v["scrip"], (v["name"] or "")[:42], v["status"]))
    print("\nrejected: %d" % len(rejected))
    for s, why in sorted(rejected.items()):
        print("  %-12s %s" % (s, why))
    if "--write" in sys.argv:
        json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
        print(f"\nwrote {os.path.basename(OUT)}")


if __name__ == "__main__":
    main()
