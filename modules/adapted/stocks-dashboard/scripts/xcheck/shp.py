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


"""Shareholding checks.

shp_neighbours  Reader A: the quarter's served FII / DII (docs/shp_engine.json, the backtest feed).
                Reader B: the SAME company's filings for the quarters either side. A holding that jumps away from both
                neighbours while the neighbours agree with each other is a one-quarter excursion: either a real in-and-out
                trade, or (far more often, measured 2026-09-28) a reading error — CENTRALBK Jun-2018 FII 0.27 -> 9.39 by the
                unnamed-remainder rule while Dec-2017 / Sep-2018 print 0.32 / 0.35 and Quantmac serves 0.29; SHREECEM
                Dec-2015 23.94 between 13.59 and 13.63. The check flags; the filing decides.
                Scope: current and former Nifty 500 members, quarters while a member, first filing of each quarter."""
import os

from . import common as C

JUMP = 3.0  # pp away from BOTH neighbours
AGREE = 1.5  # neighbours within this of each other


class ShpNeighbours(C.Check):
    id = "shp_neighbours"
    title = "Shareholding: each quarter's FII / DII vs the same company's filings either side"
    domain = "Shareholding"
    reader_a = "shp_engine.json — the quarter as served"
    reader_b = "the company's own previous and next quarterly filings"
    scope = "Nifty 500 members at the quarter, 2001 → latest; the first filing of each quarter"
    tolerance = (
        f"flag when > {JUMP:.1f} pp from both neighbours while they agree within {AGREE:.1f} pp"
    )

    def run(self):
        self.calibration = (
            "2026-09-28: of the 50 company-quarters that the Quantmac v4 comparison showed to be ours (our value "
            "off our own neighbours, theirs on them), this screen flags 12 - errors under 3 pp and alternating "
            "series (DEN 2018) slip through. A same-company test is a candidate list, not an outside reader."
        )
        feed = C.jload(os.path.join(C.DOCS, "shp_engine.json"))
        spans = {}
        for sym, rows in feed.items():
            if not isinstance(rows, list):
                continue
            first = {}
            for r in sorted(rows, key=lambda r: (r[0], r[3])):
                if r[0] % 10000 in (331, 630, 930, 1231) and r[0] not in first:
                    first[r[0]] = r
            qs = sorted(first)
            sp = spans.setdefault(sym, C.member_spans(sym))
            for i in range(1, len(qs) - 1):
                q = qs[i]
                if not any(f <= q and (t is None or q < t) for f, t in sp):
                    continue
                p, x, n = first[qs[i - 1]], first[q], first[qs[i + 1]]
                for fld, j in (("fii", 1), ("dii", 2)):
                    a, b, c = p[j], x[j], n[j]
                    if a is None or b is None or c is None:
                        continue
                    self.compared += 1
                    if (
                        abs(b - a) > JUMP
                        and abs(b - c) > JUMP
                        and abs(a - c) <= AGREE
                        and (b - a) * (b - c) > 0
                    ):
                        self.add(
                            "%s|%d|%s" % (sym, q, fld),
                            sym=sym,
                            qe=C.iso(q),
                            field=fld,
                            prev=a,
                            value=b,
                            next=c,
                            prev_qe=C.iso(qs[i - 1]),
                            next_qe=C.iso(qs[i + 1]),
                            weight=round(min(abs(b - a), abs(b - c)), 2),
                        )
                    else:
                        self.agree += 1
