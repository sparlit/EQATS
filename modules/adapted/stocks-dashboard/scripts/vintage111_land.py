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
"""§113 — annotate the §112-retracted CON cells with the PRIMARY-DOCUMENT read that settles them.

CONTEXT. §111i asked for the 59 disputed con cells to be read against the Mar-2017 filings. While
that was being done, §112 independently found the same defect from owners-basis feeds and RETRACTED
85 con heals, so the VALUES are already right — measured here: 58 of the 59 now hold the pre-heal
value, and the 59th (CANDC) was reinstated by §112c on its own filing read. Nothing needs moving.

WHAT IS STILL MISSING is evidence. §112d says the 73 retractions "stand until [a document] is read",
and §112b eliminated the text rung on a measurement that only asked the WRONG DOCUMENT:

    "The Mar-2017 filing PDFs, text layer — 0 of 4 reachable ones carried one" -> vision rung

That is true of the quarter's OWN filing. But a quarter is printed in about three filings
(memory: feedback-backfill-comparative-columns): its own, the NEXT quarter's (as the preceding-
quarter column) and the NEXT YEAR's same quarter (as the year-ago column). The 2018-era documents
are digital, and a geometry row-read gets them exactly. Measured over these 59 cells: 579 documents
fetched, and **30 cells got a clean primary owners read that way** — plus 3 more from the XBRL
owners ledger, and 3 where the comparative disagrees with both candidates (a vintage question).

So this run writes no values. It writes, onto each retracted entry, the document and row that
CONFIRM the reverted value, so those cells leave the open queue with a reason instead of waiting
for a vision pass they do not need. Cells where no readable document was found are annotated too —
measured absence of the route, never "unfillable" (§57a).

RUN: python3 -X utf8 vintage111_land.py [--write]
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from vintage111_verdicts import V  # noqa: E402

LEDGER = os.path.join(HERE, "fund_cell_fix.json")
SWEEP = "vintage108 by-product sweep 2026-08-24"
TODAY = "2026-08-25"
ROUTE = (
    "BSE announcement stream, §59b rung 3. The quarter's own filing is a scan; it is the "
    "NEXT-QUARTER and NEXT-YEAR filings that carry it as a comparative column with a text "
    "layer. Attachments resolved via stockinfo/AnnPdfOpen.aspx (the CorpAttachment base — "
    "pre-Nov-2018 files 404 on AttachHis and AttachLive)."
)
NODOC = (
    "Searched and not found, not assumed absent: the own Mar-2017 filing, the next quarter's "
    "and the next year's were all fetched and none carries the owners row in a usable text "
    "layer. The revert stands on the heal's evidence being disqualified (§112), not on a read. "
    "Open next rung: render the scanned consolidated statement and read the owners line by "
    "vision (§112d's contact-sheet method)."
)


ENTRY_RX = None


def insert_key(text, targets):
    """Insert one new key into named entries of the `retracted` list, TOUCHING NOTHING ELSE.

    ★ THIS FILE HAS NO SINGLE ENCODING STYLE. It has been written by several tools, some with
    `ensure_ascii=True` and some without, so `\u2014` and a literal em dash both appear — and
    re-serialising it with either setting rewrites ~670 untouched entries. A 1,800-line diff for 58
    annotations is how you collide with a parallel campaign writing the same ledger (measured: this
    is exactly the conflict that made the first push fail). So the edit is textual: find each
    entry, insert the new key before its closing brace, leave every other byte alone.

    `targets` maps (sym, qe, basis, found) -> the dict to insert under `confirmed_by_document`.
    """
    lines = text.split("\n")
    out, i, n = [], 0, 0
    while i < len(lines):
        if lines[i] != "  {":
            out.append(lines[i])
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j] not in ("  }", "  },"):
            j += 1
        if j >= len(lines):
            out.extend(lines[i:])
            break
        body = "\n".join(lines[i : j + 1]).rstrip(",")
        try:
            obj = json.loads(body)
        except Exception:
            out.extend(lines[i : j + 1])
            i = j + 1
            continue
        key = (obj.get("sym"), str(obj.get("qe")), obj.get("basis"), obj.get("found"))
        if key in targets and "confirmed_by_document" not in obj:
            blk = json.dumps({"confirmed_by_document": targets[key]}, indent=1, ensure_ascii=False).split("\n")[1:-1]
            out.extend(lines[i:j])
            out[-1] = out[-1] + ("" if out[-1].rstrip().endswith(",") else ",")
            out.extend("  " + b for b in blk)
            out.append(lines[j])
            n += 1
        else:
            out.extend(lines[i : j + 1])
        i = j + 1
    return "\n".join(out), n


def main():
    write = "--write" in sys.argv
    raw = open(LEDGER, encoding="utf-8").read()
    lg = json.loads(raw)
    n = {"confirmed": 0, "vintage": 0, "nodoc": 0}
    targets = {}
    for f in lg.get("retracted", []):
        if not isinstance(f, dict) or f.get("basis") != "con" or f.get("found") != SWEEP:
            continue
        key = "{}|{}".format(f["sym"], f["qe"])
        if key not in V:
            continue
        tier, note = V[key]
        if tier.startswith("PRIMARY") or tier == "XBRL-OWNERS":
            ann = {
                "on": TODAY,
                "verdict": "the reverted value is the OWNERS figure",
                "tier": tier,
                "value": f["was"],
                "evidence": note,
                "route": ROUTE
                if tier.startswith("PRIMARY")
                else "scripts/_reattr_owners.json (filings' XBRL "
                "ProfitOrLossAttributableToOwnersOfParent) — definitional, not a feed",
            }
            n["confirmed"] += 1
        elif tier == "REVERT+VINTAGE":
            ann = {
                "on": TODAY,
                "verdict": "the heal is refuted; the exact as-filed value stays OPEN",
                "tier": tier,
                "value": f["was"],
                "evidence": note,
                "route": ROUTE,
            }
            n["vintage"] += 1
        else:
            ann = {
                "on": TODAY,
                "verdict": "no readable primary document — revert stands on §112",
                "tier": tier,
                "value": f["was"],
                "evidence": NODOC + (" " + note if note else ""),
                "route": ROUTE,
            }
            n["nodoc"] += 1
        targets[(f["sym"], str(f["qe"]), f["basis"], f.get("found"))] = ann
        print("  %-12s %-9s %-18s %s" % (f["sym"], f["qe"], tier, str(f["was"])))
    new, inserted = insert_key(raw, targets)
    print("\nannotated: %s   entries edited: %d" % (n, inserted))
    # the result must still parse, and must differ from the original ONLY by the new key
    a, b = json.loads(new), lg
    for lst in ("fixes", "retracted"):
        assert len(a.get(lst, [])) == len(b.get(lst, [])), f"entry count moved in {lst}"
    for x, y in zip(a.get("fixes", []), b.get("fixes", []), strict=False):
        assert x == y, "an ACTIVE entry changed — refusing to write"
    for x, y in zip(a.get("retracted", []), b.get("retracted", []), strict=False):
        d = {k: v for k, v in x.items() if k != "confirmed_by_document"}
        assert d == y, "a retracted entry changed beyond the annotation — refusing to write"
    print("checked: fixes byte-identical, retracted differ only by confirmed_by_document")
    if write:
        open(LEDGER, "w", encoding="utf-8").write(new)
        print(f"WROTE {os.path.relpath(LEDGER, os.path.dirname(HERE))}")
    else:
        print("(dry run — pass --write)")


if __name__ == "__main__":
    main()
