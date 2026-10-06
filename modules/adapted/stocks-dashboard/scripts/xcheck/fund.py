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


"""Quarterly-results checks. Values in Rs crore; basis s = standalone, c = consolidated (owners' share for PAT).

fund_vision_xbrl  Reader A: the XBRL store (sf_fundamentals PAT authority, sf_revop revenue).
                  Reader B: vision_fills.json — a model's read of the filing PDF (a different document of the same
                  filing, read by a different method). Same quarter, same basis.
fund_pbt_tax      Reader A: stored PAT (sf_fundamentals). Reader B: the filing's own PBT and tax lines (fin/<SYM>.json
                  `x`, NSE XBRL detail) — PAT = PBT − tax (consolidated: + associates − minority, whichever
                  presentation the filer used). Catches owners/total mix-ups, wrong-quarter and scale slips.
fund_eps_shares   Reader A: stored PAT. Reader B: the company's own basic EPS × shares outstanding at quarter-end
                  (scripts/shares_history.json, the SHP filing's share count). EPS is computed by the company from
                  its weighted share count, so 5 % slack; a 10x/100x gap is a scale slip on one side."""
import json
import os

from . import common as C

BASES = (("s", 1, 0), ("c", 3, 1))  # (x key, sf_fundamentals PAT index, sf_revop revenue index)


def _near(a, b, rel, absl):
    return abs(a - b) <= max(absl, rel * max(abs(a), abs(b)))


def _in_scope(sym, qe, spans_cache):
    sp = spans_cache.get(sym)
    if sp is None:
        sp = spans_cache[sym] = C.member_spans(sym)
    return any(f <= qe and (t is None or qe < t) for f, t in sp)


def _fund():
    raw = C.jload(os.path.join(C.DOCS, "sf_fundamentals.json"))
    return {s: {r[0]: r for r in rows} for s, rows in raw.items() if isinstance(rows, list)}


class FundVisionXbrl(C.Check):
    id = "fund_vision_xbrl"
    title = "Quarterly revenue & profit: XBRL store vs PDF (vision) read"
    domain = "Quarterly results"
    reader_a = "sf_fundamentals (PAT) / sf_revop (revenue) — NSE XBRL"
    reader_b = "vision_fills.json — model read of the filing PDF"
    scope = "Nifty 500 members at quarter-end; quarters where both readers hold the same basis"
    tolerance = "within 1 % or Rs 0.5 cr"

    def run(self):
        fund = _fund()
        rev = C.jload(os.path.join(C.DOCS, "sf_revop.json"))
        vis = C.jload(os.path.join(C.DOCS, "vision_fills.json"))
        spans = {}
        for sym, qs in vis.items():
            for q, v in qs.items():
                qe = int(q)
                if not _in_scope(sym, qe, spans):
                    continue
                b = (v.get("basis") or "").lower()
                ix = {"s": (1, 0), "c": (3, 1)}.get(b)
                if not ix:
                    continue
                pairs = []
                fr = (fund.get(sym) or {}).get(qe)
                if fr is not None and fr[ix[0]] is not None and v.get("pat") is not None:
                    pairs.append(("pat", fr[ix[0]], v["pat"]))
                rr = (rev.get(sym) or {}).get(q)
                if rr and rr[ix[1]] is not None and v.get("rev") is not None:
                    pairs.append(("rev", rr[ix[1]], v["rev"]))
                for fld, a, bv in pairs:
                    self.compared += 1
                    if _near(a, bv, 0.01, 0.5):
                        self.agree += 1
                        continue
                    ratio = a / bv if bv else None
                    self.add(
                        "%s|%d|%s|%s" % (sym, qe, b, fld),
                        sym=sym,
                        qe=C.iso(qe),
                        basis=b,
                        field=fld,
                        a=a,
                        b=bv,
                        ratio=round(ratio, 4) if ratio else None,
                        weight=round(abs(a - bv), 2),
                    )


class FundPbtTax(C.Check):
    id = "fund_pbt_tax"
    title = "Stored profit vs the filing's own PBT − tax"
    domain = "Quarterly results"
    reader_a = "sf_fundamentals PAT (owners' share for consolidated)"
    reader_b = "fin/<SYM>.json x: PBT, tax, associates, minority (NSE XBRL detail lines)"
    scope = "Nifty 500 members at quarter-end, quarters with PBT and tax filed"
    tolerance = "any presentation within 2 % or Rs 1 cr"

    def run(self):
        fund = _fund()
        ever = C.ever_members()
        spans = {}
        for sym in sorted(ever):
            p = os.path.join(C.DOCS, "fin", sym + ".json")
            if not os.path.exists(p):
                continue
            try:
                x = json.load(open(p, encoding="utf-8")).get("x") or {}
            except ValueError:
                continue
            for q, bases in x.items():
                qe = int(q)
                if not _in_scope(sym, qe, spans):
                    continue
                fr = (fund.get(sym) or {}).get(qe)
                if fr is None:
                    continue
                for bk, pi, _ in BASES:
                    d = bases.get(bk) or {}
                    pat = fr[pi]
                    if pat is None or d.get("pbt") is None or d.get("tax") is None:
                        continue
                    pbt, tax = d["pbt"], d["tax"]
                    asc = d.get("assoc") or 0.0
                    nci = d.get("nci") or 0.0
                    cands = {"pbt-tax": pbt - tax}
                    if bk == "c":
                        cands.update(
                            {
                                "pbt-tax+assoc-nci": pbt - tax + asc - nci,
                                "pbt-tax-nci": pbt - tax - nci,
                                "pbt-tax+assoc": pbt - tax + asc,
                            }
                        )
                    self.compared += 1
                    if any(_near(pat, v, 0.02, 1.0) for v in cands.values()):
                        self.agree += 1
                        continue
                    best = min(cands.items(), key=lambda kv: abs(kv[1] - pat))
                    self.add(
                        "%s|%d|%s" % (sym, qe, bk),
                        sym=sym,
                        qe=C.iso(qe),
                        basis=bk,
                        pat=pat,
                        pbt=pbt,
                        tax=tax,
                        assoc=asc or None,
                        nci=nci or None,
                        closest=[best[0], round(best[1], 2)],
                        ratio=round(pat / best[1], 4) if best[1] else None,
                        weight=round(abs(pat - best[1]), 2),
                    )


class FundEpsShares(C.Check):
    id = "fund_eps_shares"
    title = "Stored profit vs the company's EPS × shares outstanding"
    domain = "Quarterly results"
    reader_a = "sf_fundamentals PAT (owners' share for consolidated)"
    reader_b = (
        "fin x eps_b (company-computed basic EPS) × shares_history (SHP share count at quarter-end)"
    )
    scope = "Nifty 500 members at quarter-end, quarters with basic EPS and a share count"
    tolerance = "within 5 % or Rs 1 cr (weighted vs period-end shares)"

    def run(self):
        fund = _fund()
        ever = C.ever_members()
        spans = {}
        sh = C.jload(os.path.join(C.HERE, "shares_history.json"))
        for sym in sorted(ever):
            p = os.path.join(C.DOCS, "fin", sym + ".json")
            shs = sh.get(sym) or {}
            if not os.path.exists(p) or not shs:
                continue
            try:
                x = json.load(open(p, encoding="utf-8")).get("x") or {}
            except ValueError:
                continue
            for q, bases in x.items():
                qe = int(q)
                if not _in_scope(sym, qe, spans):
                    continue
                fr = (fund.get(sym) or {}).get(qe)
                cnt = (shs.get(C.iso(qe)) or [None])[0]
                if fr is None or not cnt:
                    continue
                for bk, pi, _ in BASES:
                    d = bases.get(bk) or {}
                    pat = fr[pi]
                    eps = d.get("eps_b")
                    if pat is None or eps is None or eps == 0:
                        continue
                    implied = eps * cnt / 1e7
                    self.compared += 1
                    if _near(pat, implied, 0.05, 1.0):
                        self.agree += 1
                        continue
                    ratio = pat / implied if implied else None
                    self.add(
                        "%s|%d|%s" % (sym, qe, bk),
                        sym=sym,
                        qe=C.iso(qe),
                        basis=bk,
                        pat=pat,
                        eps=eps,
                        shares=cnt,
                        implied=round(implied, 2),
                        ratio=round(ratio, 4) if ratio else None,
                        weight=round(abs(pat - implied), 2),
                    )
