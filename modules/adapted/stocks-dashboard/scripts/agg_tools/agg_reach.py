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
"""MEASURE what each aggregator actually reaches, per company, per basis. Nothing is assumed.

The §60a discipline: "screener does not have all -- say what it has". Same here. Reach is a
property of the COMPANY as much as the site (Moneycontrol holds 111 standalone quarters for
WESTLIFE and 51 consolidated ones), so this samples real companies off the open-cell list rather
than quoting one number per site.

Columns: how many QUARTERS the site holds and the oldest/newest it prints, then the same for the
ANNUAL table. A blank means the site answered but held nothing for that basis; a note says which.

  python3 -X utf8 scripts/agg_tools/agg_reach.py --syms WESTLIFE,SPICEJET,...  [--md out.md]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import agg_sources as A  # noqa: E402

SITES = ("mc", "tl", "tt")


def span(d):
    return ("%d" % min(d), "%d" % max(d)) if d else ("-", "-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--syms", required=True)
    ap.add_argument("--out", default=os.path.join(HERE, "_agg_reach.json"))
    ap.add_argument("--md")
    a = ap.parse_args()

    rows = []
    for sym in a.syms.split(","):
        for site in SITES:
            for basis, con in (("STD", False), ("CON", True)):
                q, qn = A.read(site, sym, con)
                y, yn = A.read_annual(site, sym, con)
                q0, q1 = span(q)
                y0, y1 = span(y)
                rows.append(
                    {
                        "sym": sym,
                        "site": site,
                        "basis": basis,
                        "quarters": len(q),
                        "q_oldest": q0,
                        "q_newest": q1,
                        "annuals": len(y),
                        "a_oldest": y0,
                        "a_newest": y1,
                        "q_note": qn,
                        "a_note": yn,
                    }
                )
                print(
                    "%-11s %-3s %-3s  Q %3d %8s..%-8s  A %2d %8s..%-8s"
                    % (sym, site, basis, len(q), q0, q1, len(y), y0, y1)
                )
                sys.stdout.flush()
    json.dump(rows, open(a.out, "w"), indent=1)

    if a.md:
        lines = [
            "| company | site | basis | quarters | oldest Q | newest Q | FYs | oldest FY |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                "| %s | %s | %s | %d | %s | %s | %d | %s |"
                % (
                    r["sym"],
                    r["site"],
                    r["basis"],
                    r["quarters"],
                    r["q_oldest"],
                    r["q_newest"],
                    r["annuals"],
                    r["a_oldest"],
                )
            )
        open(a.md, "w").write("\n".join(lines) + "\n")
        print(f"\nwrote {a.md}")


if __name__ == "__main__":
    main()
