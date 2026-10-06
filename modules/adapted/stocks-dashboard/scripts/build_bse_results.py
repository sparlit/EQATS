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
"""Build docs/bse_results.json — a SLIM BSE-only payload in the SAME shape as quarterly_results.json's
`co`, so the Quarterly Results page merges BSE-listed-only companies (Cella Space, NSDL, …) in one line.

Joins three BSE side-files (all produced separately):
  - docs/bse_universe.json     — name, sector, mcap per BSE-only scrip
  - docs/bse_fundamentals.json — quarterly {rev,pat,ann,basis} per scrip (OCR of the co's own filing)
  - docs/bse_prices.bin        — daily closes per scrip (BSE bhavcopy) → result-day reaction + since-drift

Quarters list is READ FROM quarterly_results.json so the q-array indices line up exactly. Each emitted
co record mirrors the NSE payload:  {n,s,i,m,f,x,e, bse:1, q:[[revS,opS,patS,revC,opC,patC,ann,rx,sr]|null,…]}
BSE small-caps are standalone → we put the same value in the std AND con slots (op left null); `bse:1`
flags the row so the page can show a BSE badge. Keyed by BSE ticker; skips any ticker already on NSE.

Run: python -X utf8 scripts/build_bse_results.py
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # §181 BSE headers
import datetime
import gzip
import json
import os

import reaction_timing as RT

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "..", "docs")
QR = os.path.join(D, "quarterly_results.json")
UNIV = os.path.join(D, "bse_universe.json")
FUND = os.path.join(D, "bse_fundamentals.json")
PX = os.path.join(D, "bse_prices.bin")
FAILS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_bse_fund_fail.json")
OUT = os.path.join(D, "bse_results.json")
PDF_ONLY_MIN = 2  # fail attempts before a filed co is flagged "PDF only" (not parseable)

FIN_SECTORS = {"Finance", "Banks", "Bank", "Financial Services", "NBFC"}


def load_prices():
    if os.path.exists(PX):
        try:
            return json.loads(gzip.decompress(open(PX, "rb").read()).decode("utf8"))
        except Exception:
            pass
    return {"px": {}, "end": 0}


def _day(i):
    return datetime.date(i // 10000, i // 100 % 100, i % 100)


def ann_ok(qe, ann):
    """A results filing date must fall AFTER its quarter end and within ~13 months of it. Anything else
    is a mis-read (MILEFUR Sep-23 carried ann 20260318) and must neither be shown nor price a reaction."""
    try:
        return bool(ann) and 0 < (_day(ann) - _day(int(qe))).days <= 400
    except ValueError:
        return False


MAX_GAP = 10  # calendar days: a close further away than this is not "the session" around the filing


def reaction(series, ann, after=None):
    """(result-day move %, since-result drift %) from a scrip's close series and an ann date int.
    Both the reaction bar and the PRIOR close must sit within MAX_GAP days of the filing — a suspended
    or thinly-traded scrip otherwise compared against a close from years earlier (BIRLACOT +16,284%)."""
    if not series or not ann:
        return None, None
    d, c = series["d"], series["c"]
    # after-close filing (broadcast after 15:30) -> the NEXT session is the reaction bar (runbook §193)
    j = RT.reaction_index(d, ann, after)
    if j is None or j == 0:
        return None, None
    if (_day(d[j]) - _day(ann)).days > MAX_GAP or (_day(ann) - _day(d[j - 1])).days > MAX_GAP:
        return None, None
    rd = (c[j] / c[j - 1] - 1) * 100 if c[j - 1] else None  # result-day vs prior close
    sr = (c[-1] / c[j] - 1) * 100 if c[j] else None  # drift to latest close
    return (round(rd, 2) if rd is not None else None, round(sr, 2) if sr is not None else None)


def main():
    qr = json.load(open(QR, encoding="utf-8"))
    quarters = list(qr["quarters"])  # e.g. [20260630, 20260331, …] newest-first
    # CALENDAR RULE (§218): a new quarter opens on its first IST day even before quarterly_results.json is rebuilt —
    # else a BSE-only first filer (HIIL Sep-2026) has no column to land in. Same window length; the page lines the two
    # files up by quarter while they differ.
    import build_quarterly_results as _BQ

    while quarters and quarters[0] < _BQ.last_ended_qe(_BQ.ist_today()):
        quarters = [_BQ.next_qe(quarters[0])] + quarters[:-1]
    qidx = {int(q): i for i, q in enumerate(quarters)}
    nse_syms = set(qr["co"].keys())

    univ = {str(r[0]): r for r in json.load(open(UNIV, encoding="utf-8"))["rows"]}  # scrip -> row
    fund = json.load(open(FUND, encoding="utf-8"))["px"] if os.path.exists(FUND) else {}
    prices = load_prices()["px"]

    import bse_resolve

    co, overlay = {}, {}

    def row(rec, qe, series, scrip):
        """q row [revS,opS,patS,revC,opC,patC,ann,rx,sr]: the figures go ONLY into their own basis
        slots — copying one number into both made the page compare a consolidated quarter with a
        standalone one (664 mixed YoY pairs, CELLA +26,474%)."""
        ann = rec.get("ann") or 0
        if not ann_ok(qe, ann):
            ann = 0
        rx, sr = reaction(series, ann, RT.after_close(ann, scrip=scrip)) if ann else (None, None)
        v = [rec.get("rev"), rec.get("op"), rec.get("pat")]
        out = (([None] * 3 + v) if rec.get("basis") == "C" else (v + [None] * 3)) + [
            ann or None,
            rx,
            sr,
        ]
        if rec.get("prov"):
            out.append(
                1
            )  # [9] = provisional Apr-Sep half, not yet closed by the Mar filing (runbook §195, Option A)
        return out

    for code, qs in fund.items():
        u = univ.get(code)
        if not u:
            continue
        scrip, tkr, name, isin, grp, fv, mc, sec = u
        tkr = bse_resolve.bse_key(tkr)  # 'GSTL-BSE' when GSTL is an unrelated NSE company
        if not tkr or tkr in co:
            continue
        # ⚠️ A ticker that IS an NSE symbol must never SHADOW the NSE company's row — but dropping it
        # outright strands the numbers. Our NSE-keyed pipeline and the BSE grind cover different
        # companies well, and for a dual-listed small-cap the BSE grind often reads a quarter the NSE
        # side has no XBRL for. Before 2026-08-18 those cells simply could not reach the page: 47
        # tickers / 90 quarter-cells, and they were the BIGGEST names in the pending list (FREDUN
        # ₹2,386cr, KMCSHIL ₹2,312cr, INDOKEM, MIIL…), which is why the "+N coming" tile was full of
        # real companies that had in fact already been read. Emit them as an OVERLAY instead — the
        # page applies it to EMPTY cells only, exactly like vision_fills.json, so a real NSE/XBRL
        # value always wins and the no-shadow rule is still honoured.
        if tkr in nse_syms:
            e = overlay.setdefault(tkr, {})
            series_o = prices.get(code)
            for qe, rec in qs.items():
                if qidx.get(int(qe)) is None:
                    continue
                if rec.get("rev") is None and rec.get("pat") is None and rec.get("op") is None:
                    continue
                e[str(int(qe))] = row(rec, qe, series_o, code)
            if not e:
                overlay.pop(tkr, None)
            continue
        q = [None] * len(quarters)
        series = prices.get(code)
        any_num = False
        for qe, rec in qs.items():
            qi = qidx.get(int(qe))
            if qi is None:
                continue
            q[qi] = row(rec, qe, series, code)
            any_num = True
        if not any_num:
            continue
        f = 1 if (sec in FIN_SECTORS) else 0
        co[tkr] = {
            "n": name,
            "s": sec or "Other",
            "i": sec or "Other",
            "m": mc,
            "f": f,
            "x": 0,
            "e": "",
            "bse": 1,
            "cd": int(scrip),
            "q": q,
        }

    # "PDF only": BSE tickers that FILED a result but resisted OCR ≥ PDF_ONLY_MIN times — their number
    # isn't merely queued (scanned/odd-layout PDF), so the page labels them honestly instead of "coming".
    pdf_only = []
    try:
        fails = json.load(open(FAILS))
        for code, n in fails.items():
            if n >= PDF_ONLY_MIN and str(code) in univ:
                tkr = bse_resolve.bse_key(univ[str(code)][1])
                if tkr and tkr not in co and tkr not in nse_syms:
                    pdf_only.append(tkr)
    except Exception:
        pass

    ist = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)
    out = {
        "updated": ist.strftime("%Y-%m-%d %H:%M IST"),
        "asof": qr.get("asof"),
        "quarters": quarters,
        "count": len(co),
        "co": co,
        "pdf_only": sorted(set(pdf_only)),
        "nse_overlay": overlay,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(
        "WROTE %s: %d BSE-only companies with numbers, %d PDF-only, %d dual-listed overlay tickers "
        "(%d quarter-cells that would otherwise be unreachable)"
        % (
            os.path.normpath(OUT),
            len(co),
            len(pdf_only),
            len(overlay),
            sum(len(v) for v in overlay.values()),
        )
    )


if __name__ == "__main__":
    main()
