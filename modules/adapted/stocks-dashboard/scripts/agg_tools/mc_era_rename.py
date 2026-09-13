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
"""RUNG 3 of the era resolver: reach a company through its NSE symbol-change history.

46 companies (283 open cells) survived both rungs of mc_era.resolve — and the list gives the game
away: CASTROL, COLGATE, CEAT, NIIT, TUBEINVEST, GESHIPPING are all very much alive on Moneycontrol.
They fail because our sf_fundamentals key is the symbol that traded THEN and MC prints the symbol
that trades NOW (CASTROL -> CASTROLIND, TUBEINVEST -> TIINDIA), while rung 2's ISIN lookup goes
through `bse_master.scrip_id == our symbol`, which is the old ticker too. Both rungs ask the present
about a name only the past used.

NSE publishes the mapping itself — `archives.nseindia.com/content/equities/symbolchange.csv`, the
same file scripts/detect_renames.py already treats as authoritative for old->new pairs. Chains are
walked transitively (a symbol can be renamed twice) with a visited-set, and the company NAME on each
row gives a second query for MC's autosuggest when the new symbol still does not match.

WHAT MAKES THIS SAFE. A rename is a claim about identity, and this module never gets to make that
claim stick: whatever it resolves still has to pass GATE E, whose E1 requires the resolved series to
reproduce >=8 of the values we store UNDER THE OLD SYMBOL. A wrong rename produces a different
company's numbers and fails on the first anchor. The rename only decides where to look.

  python3 -X utf8 scripts/agg_tools/mc_era_rename.py --reach _era_reach_0214.json --out /tmp/r3.json
"""
import argparse
import csv
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import agg_sources as A  # noqa: E402
import mc_era as E  # noqa: E402

NSE_SC = "https://archives.nseindia.com/content/equities/symbolchange.csv"
MON = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def symbol_changes():
    """-> ({OLD: NEW}, {SYMBOL: company name}). Empty on failure -- never fabricated."""
    txt = A._get("archives.nseindia.com", NSE_SC, 1.0, "nse", "symbolchange", ttl=86400 * 7)
    if not txt:
        return {}, {}
    nxt, names = {}, {}
    for r in csv.reader(io.StringIO(txt)):
        cells = [c.strip() for c in r]
        di = next((i for i, c in enumerate(cells) if re.match(r"^\d{1,2}-[A-Za-z]{3}-\d{4}$", c)), None)
        if di is None or di < 2:
            continue
        old, new = cells[di - 2].upper(), cells[di - 1].upper()
        if not old or not new:
            continue
        nxt[old] = new
        if di >= 3 and cells[di - 3]:
            names[old] = names.setdefault(new, cells[di - 3])
    return nxt, names


def current_symbol(sym, nxt):
    """Walk the rename chain to its end. Cycles are impossible in a correct file; guard anyway."""
    cur, seen, chain = sym, {sym}, []
    while cur in nxt and nxt[cur] not in seen:
        cur = nxt[cur]
        seen.add(cur)
        chain.append(cur)
    return cur, chain


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reach", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    reach = json.load(open(a.reach if os.path.isabs(a.reach) else os.path.join(HERE, a.reach)))
    unres = sorted([s for s, v in reach.items() if not v.get("resolved")], key=lambda s: -reach[s]["gaps"])
    nxt, names = symbol_changes()
    print("NSE symbolchange: %d old->new pairs, %d names\n" % (len(nxt), len(names)))
    if not nxt:
        print("symbolchange.csv unavailable -- nothing resolved, and nothing guessed.")
        json.dump({}, open(a.out, "w"))
        return

    idc = json.load(open(E._ISIN_CACHE)) if os.path.exists(E._ISIN_CACHE) else {}
    out = {}
    print("%-12s %-14s %-8s %-6s %s" % ("OLD", "CURRENT", "sc_id", "qtrs", "how"))
    for sym in unres:
        cur, chain = current_symbol(sym, nxt)
        rec = {"gaps": reach[sym]["gaps"], "chain": chain or None, "current": cur}
        ident = None
        if cur != sym:
            hit = A.mc_id(cur)  # exact-symbol gate on the NEW name
            if hit and hit.get("sc_id"):
                ident = {
                    "sc_id": hit["sc_id"],
                    "via": "nse-symbolchange",
                    "isin": hit.get("isin"),
                    "mc_sym": cur,
                    "note": "NSE symbolchange {} -> {}; MC exact-symbol match on the current name".format(
                        " -> ".join([sym, *chain]), cur
                    ),
                }
        if ident is None:  # last try: the company NAME
            nm = names.get(sym) or names.get(cur)
            if nm:
                for r in E._sugg_rows(nm, "name_"):
                    if r["sc_id"] and r["sym"] and r["sym"].upper() in (cur, sym):
                        ident = {
                            "sc_id": r["sc_id"],
                            "via": "nse-name",
                            "isin": r["isin"],
                            "mc_sym": r["sym"],
                            "note": "NSE symbolchange name {!r}; MC row's own symbol is {}".format(nm, r["sym"]),
                        }
                        break
        if ident:
            series, _note = E.quarters(ident, con=False)
            rec.update(
                {
                    "resolved": True,
                    "sc_id": ident["sc_id"],
                    "via": ident["via"],
                    "periods": len(series),
                    "oldest": min(series) if series else None,
                }
            )
            idc[sym] = ident
            print("%-12s %-14s %-8s %-6d %s" % (sym, cur, ident["sc_id"], len(series), ident["via"]))
        else:
            rec["resolved"] = False
            rec["why"] = (
                (f"no rename recorded for {sym}")
                if cur == sym
                else (f"renamed to {cur} but MC has no exact match for it either")
            )
            print("%-12s %-14s %-8s %-6s %s" % (sym, cur if cur != sym else "-", "-", "-", rec["why"][:52]))
        out[sym] = rec
        sys.stdout.flush()

    json.dump(idc, open(E._ISIN_CACHE, "w"), indent=0, sort_keys=True)
    json.dump(out, open(a.out, "w"), indent=1, sort_keys=True)
    n = sum(1 for v in out.values() if v.get("resolved"))
    print(
        "\nresolved %d of %d (%d cells) -> %s"
        % (n, len(out), sum(v["gaps"] for v in out.values() if v.get("resolved")), a.out)
    )


if __name__ == "__main__":
    main()
