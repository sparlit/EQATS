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
"""ADJUDICATE the issuer-sweep seams: which are the 93d defect, and which must NEVER be merged.

Input: scripts/_isin_seam_evidence.json (isin_seam_evidence.py — NSE's own dated files).
Output: scripts/_isin_seam_verdicts.json + a table.

A shared ISIN issuer proves the two securities belong to one legal entity. It does NOT prove the
bin should join them, so every seam is put through refusals first and only then corroborated:

REFUSALS (any one is decisive)
  same-isin      the two keys carry the SAME full ISIN, so this is not the face-value class at
                 all — the auto-merge's input was missing, not its comparison wrong. Kept out of
                 this campaign and reported on its own.
  cotrade        the tapes share sessions: a DVR or a partly-paid line beside the ordinary share.
                 One company cannot trade under two NSE symbols at once (93b), so co-trading is
                 decisive evidence AGAINST a rename.
  old-alive      the OLD symbol is in TODAY's EQUITY_L: it now belongs to a live company and may
                 be a re-issue (89). 30-4c already refuses to alias one; so does this.
  overlap        main segments overlap even without a shared session.

CORROBORATION — the issuer prefix is the screen; a merge needs a second, independent leg:
  symchg         NSE's own rename register links the two symbols (decisive when present; the two
                 pairs 93d proved are NOT in it, so absence proves nothing)
  prevclose      the new symbol's first PREVCLOSE reproduces the old symbol's last close exactly
                 to the paise at a face-value factor. CONFIRMATION only — 93c measured its
                 false-positive rate as useless for discovery
  seam-isin      the security traded on the new key's first session carries this issuer's ISIN,
                 read straight out of that day's bhavcopy
  name           EQUITY_L gives both symbols the same company name
  listed=first   EQUITY_L's DATE OF LISTING for the new symbol IS the new key's first bar — the
                 new series listed exactly where the old one stopped
  tape-continuous  the new key's ISIN was read on a date its OWN unbroken tape reaches back from
                 the seam. NSE can only re-issue a symbol after the holder delists, which leaves
                 a hole; an unbroken daily tape from the seam to the read date therefore means
                 one company held that symbol the whole time, so the ISIN read later is the ISIN
                 of the company that took over at the seam. This is the series-reproduction
                 standard (89/90k) rather than a name resemblance, and it is what decides a pair
                 whose seam predates 2011 (SRIADIKARI->SABTN: the bhavcopy carried no ISIN column
                 in 2007, but SABTN's tape runs unbroken 2007-11-16 -> 2024-01-23 and carries
                 INE416A01036 once the column exists).

Verdict: CONFIRMED with >=2 legs or a symchg row; SINGLE-LEG with exactly one (reported, landed
only after a hand read); OPEN with none.

Run:  python3 scripts/isin_seam_adjudicate.py
"""
import collections
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EV = os.path.join(HERE, "_isin_seam_evidence.json")
LIVE_EQ = os.path.join(HERE, "_live", "equity_l_live.csv")
OUT = os.path.join(HERE, "_isin_seam_verdicts.json")


def norm_name(s):
    s = (s or "").upper()
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(
        r"\b(LIMITED|LTD|PVT|PRIVATE|THE|COMPANY|CO|INDIA|CORPORATION|CORP|"
        r"INDUSTRIES|IND|AND)\b",
        " ",
        s,
    )
    return re.sub(r"\s+", " ", s).strip()


def live_symbols():
    out = set()
    if not os.path.exists(LIVE_EQ):
        return out
    with open(LIVE_EQ, encoding="utf-8", errors="replace") as fh:
        rd = csv.reader(fh)
        next(rd)
        for r in rd:
            if r:
                out.add(r[0].strip().upper())
    return out


def eq_field(seam, sym, field):
    """The field's value for `sym` from whichever staged list holds it (live wins, then newest)."""
    for tag in ["live", *sorted((t for t in seam["equityL"] if t != "live"), reverse=True)]:
        row = seam["equityL"].get(tag, {}).get(sym)
        if row and row.get(field):
            return row[field], tag
    return None, None


def ymd_of(listed):
    """'31-MAR-2008' / '19-Jul-95' -> 20080331. None when unparseable."""
    import datetime

    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            d = datetime.datetime.strptime((listed or "").strip().title(), fmt).date()
            if d.year > 2050:
                d = d.replace(year=d.year - 100)
            return int(d.strftime("%Y%m%d"))
        except ValueError:
            pass
    return None


def tape_continuous(seam, keyrec):
    """Is the new key's ISIN read from a date its own unbroken tape reaches back from the seam?

    -> (bool, note). `bin` means the ISIN came off one of that symbol's own bhavcopy rows, which
    only carry the column from 2011; the other sources carry their own date."""
    if not keyrec or len(keyrec["segments"]) != 1:
        return False, None
    seg = keyrec["segments"][0]
    if seg[0] != seam["newFirst"]:
        return False, None
    src = seam["newIsinSrc"]
    if src == "bin":
        read_from, read_to = 20110101, seg[1]
        ok = read_to >= read_from
        when = ">=2011 (bhavcopy ISIN column), tape ends %d" % seg[1]
    elif src == "equity_l_live":
        ok, when = True, "today's EQUITY_L, tape still open at %d" % seg[1]
    else:
        cap = int(src.split("_")[-1])
        ok, when = seg[0] <= cap <= seg[1], "capture %d inside %d..%d" % (cap, seg[0], seg[1])
    return ok, {"segment": seg, "isinSrc": src, "read": when}


def adjudicate(seam, live, keyrec=None):
    refusals, legs, notes = [], [], {}
    if seam["sameIsin"]:
        refusals.append("same-isin")
    if seam["kind"] == "cotrade":
        refusals.append("cotrade")
    if seam["gapDays"] <= 0:
        refusals.append("overlap")
    if seam["old"] in live:
        refusals.append("old-alive")

    if seam["symchg"]:
        pair = {(r["old"], r["new"]) for r in seam["symchg"]}
        legs.append("symchg")
        notes["symchg"] = sorted("{}->{} {}".format(r["old"], r["new"], r["date"]) for r in seam["symchg"])
        notes["symchgDirect"] = (seam["old"], seam["new"]) in pair
    if seam["prevcloseFactors"]:
        legs.append("prevclose")
        notes["prevclose"] = {
            "closeOld": seam["bhavOld"]["close"],
            "prevcloseNew": seam["bhavNew"]["prevclose"],
            "factors": seam["prevcloseFactors"],
        }
    if (seam["bhavNew"].get("isin") or "").startswith(seam["issuer"]):
        legs.append("seam-isin")
        notes["seamIsin"] = {"symbol": seam["bhavNew"]["symbol"], "isin": seam["bhavNew"]["isin"]}
    n_old, t_old = eq_field(seam, seam["old"], "name")
    n_new, t_new = eq_field(seam, seam["new"], "name")
    if n_old and n_new and norm_name(n_old) == norm_name(n_new):
        legs.append("name")
        notes["name"] = {"old": f"{n_old} ({t_old})", "new": f"{n_new} ({t_new})"}
    l_new, t_l = eq_field(seam, seam["new"], "listed")
    if l_new and ymd_of(l_new) == seam["newFirst"]:
        legs.append("listed=first")
        notes["listed"] = {"listed": l_new, "src": t_l, "newFirst": seam["newFirst"]}
    ok, note = tape_continuous(seam, keyrec)
    if ok:
        legs.append("tape-continuous")
        notes["tapeContinuous"] = note
    f_old, _ = eq_field(seam, seam["old"], "face")
    f_new, _ = eq_field(seam, seam["new"], "face")
    if f_old and f_new:
        notes["face"] = f"{f_old} -> {f_new}"

    if refusals:
        v = "REFUSED"
    elif "symchg" in legs or len(legs) >= 2:
        v = "CONFIRMED"
    elif legs:
        v = "SINGLE-LEG"
    else:
        v = "OPEN"
    return v, refusals, legs, notes


def main():
    E = json.load(open(EV))
    SW = json.load(open(os.path.join(HERE, "_isin_issuer_sweep.json")))
    keyrecs = {(g["issuer"], k["key"]): k for g in SW["groups"] for k in g["keys"]}
    live = live_symbols()
    print("live EQUITY_L: %d symbols" % len(live))
    out = []
    for s in E["seams"]:
        v, refusals, legs, notes = adjudicate(s, live, keyrecs.get((s["issuer"], s["new"])))
        out.append(dict(s, verdict=v, refusals=refusals, legs=legs, notes=notes))

    json.dump({"sfEnd": E["sfEnd"], "seams": out}, open(OUT, "w"), indent=1, sort_keys=True)
    c = collections.Counter(r["verdict"] for r in out)
    print("%d seams: %s\n" % (len(out), dict(c)))
    for v in ("CONFIRMED", "SINGLE-LEG", "OPEN", "REFUSED"):
        rows = [r for r in out if r["verdict"] == v]
        if not rows:
            continue
        print("=== %s (%d)" % (v, len(rows)))
        for r in sorted(rows, key=lambda x: (x["issuer"],)):
            print(
                "  %-8s %-12s -> %-12s gap %5d  %-28s %s"
                % (
                    r["issuer"],
                    r["old"],
                    r["new"],
                    r["gapDays"],
                    ",".join(r["legs"]) or "-",
                    "REFUSED:" + ",".join(r["refusals"]) if r["refusals"] else (r["notes"].get("face") or ""),
                )
            )
        print()
    print("wrote " + OUT)


if __name__ == "__main__":
    main()
