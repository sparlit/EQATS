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
"""Bake docs/quarterly_results.json — the single slim payload behind docs/quarterly-results.html.

Per company, for the last N_Q calendar quarters: Revenue / Operating Profit (std+con, from
sf_revop.json), owners-attributable PAT (std+con, from sf_fundamentals.json — NEVER revop's PAT),
announce date, result-day price reaction and since-result drift (from the price bin), plus
sector / industry / mcap / index-membership tags and a cadence-PREDICTED next result date.

Price bin: env SF_BIN if set, else docs/sf_stock_data.bin. In CI the workflow downloads the fresh
`data` release asset first (the committed docs bin is a stale snapshot — runbook §0). Reaction uses
the 15:30-gated ann-date (runbook §12), so close(annDay)/close(prev trading day) is look-ahead-clean
for pre-close AND post-close filings alike.

Output (compact):
{"updated","asof","quarters":[QE ints newest-first ×13],
 "co":{SYM:{"n":name,"s":sector,"i":industry,"m":mcap_cr,"f":0|1 bank/nbfc,"x":index bitmask,
            "e":"YYYY-MM-DD"|0 predicted next result date,
            "q":[null | [revS,opS,patS,revC,opC,patC,ann,rx,sr] ×13 aligned to quarters]}}}
x bits: 1=Nifty50 2=Nifty100 4=Nifty500 8=Midcap150 16=Smallcap250 32=F&O.
rx = % move close(annDay) vs prior close; sr = % drift close(annDay) -> asof (recent quarters only).

Run: python -X utf8 scripts/build_quarterly_results.py
"""
import contextlib
import datetime
import gzip
import json
import os
import statistics
from bisect import bisect_left

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
OUT = os.path.join(DOCS, "quarterly_results.json")
N_Q = 13
SR_WINDOW_DAYS = 140  # bake since-result drift only for recent announcements
QE_MONTHS = (3, 6, 9, 12)


def jload(p):
    return json.load(open(p, encoding="utf-8"))


def qe_to_date(qe):
    return datetime.date(qe // 10000, (qe // 100) % 100, qe % 100)


def prev_qe(qe):
    y, m = qe // 10000, (qe // 100) % 100
    i = QE_MONTHS.index(m)
    y2, m2 = (y - 1, 12) if i == 0 else (y, QE_MONTHS[i - 1])
    last = {3: 31, 6: 30, 9: 30, 12: 31}[m2]
    return y2 * 10000 + m2 * 100 + last


def next_qe(qe):
    y, m = qe // 10000, (qe // 100) % 100
    i = QE_MONTHS.index(m)
    y2, m2 = (y + 1, 3) if i == 3 else (y, QE_MONTHS[i + 1])
    last = {3: 31, 6: 30, 9: 30, 12: 31}[m2]
    return y2 * 10000 + m2 * 100 + last


def main():
    fund = jload(os.path.join(DOCS, "sf_fundamentals.json"))
    revop = jload(os.path.join(DOCS, "sf_revop.json"))
    klass = jload(os.path.join(DOCS, "sector_classification.json"))

    bin_path = os.environ.get("SF_BIN") or os.path.join(DOCS, "sf_stock_data.bin")
    big = json.loads(gzip.decompress(open(bin_path, "rb").read()))
    px, bmeta = big["data"], big.get("meta", {})
    asof = big.get("end", "")
    int(asof.replace("-", "")) if asof else 0
    print("price bin:", bin_path, "end =", asof)

    # Re-key the price bin to CURRENT tickers. The bin lags a rename (it is refreshed on its own
    # cadence) so it can still hold the OLD key, while DATA_RUNBOOK §30 step 4 has already moved the
    # fundamentals/revop rows to the NEW one. `syms` below comes from those files, so the new key finds
    # no series and the company is SKIPPED OFF THE PAGE ALTOGETHER (GUJENERGY, ONIDA — 2026-07-17).
    # Fill-only: a real current-key series always wins, so this self-disarms once the bin catches up.
    carried = 0
    for _old, _new in (jload(os.path.join(HERE, "_rename_map.json")) or {}).items():
        if _old in px and _new not in px:
            px[_new] = px[_old]
            if _old in bmeta and _new not in bmeta:
                bmeta[_new] = bmeta[_old]
            carried += 1
    if carried:
        print("carried %d renamed price series onto their current ticker (bin lags _rename_map)" % carried)

    slim_meta = {}
    slim_p = os.path.join(DOCS, "dash_slim.bin")
    if os.path.exists(slim_p):
        try:
            sm = json.loads(gzip.decompress(open(slim_p, "rb").read())).get("meta", {})
            for k, v in sm.items():
                slim_meta[str(v.get("symbol") or k.split(".")[0]).upper()] = v
        except Exception as ex:
            print("WARN dash_slim unreadable:", ex)

    # --- index membership bitmask (latest snapshots; current-name labels) ---
    bits = {}

    def tag(symbols, bit):
        for s in symbols:
            bits[s] = bits.get(s, 0) | bit

    try:
        ih = jload(os.path.join(HERE, "indices_history.json"))
        for name, bit in (
            ("Nifty 50", 1),
            ("Nifty 100", 2),
            ("Nifty 500", 4),
            ("Nifty Midcap 150", 8),
            ("Nifty Smallcap 250", 16),
        ):
            snaps = ih.get(name) or []
            if snaps:
                tag(snaps[-1]["symbols"], bit)
    except Exception as ex:
        print("WARN indices_history:", ex)
    try:
        fh = jload(os.path.join(HERE, "fno_history.json"))
        if fh:
            tag(fh[-1]["symbols"], 32)
    except Exception as ex:
        print("WARN fno_history:", ex)

    # --- quarter axis: latest QE with any filing, walk back N_Q ---
    latest = 0
    for rows in fund.values():
        for r in rows:
            if (
                isinstance(r, list)
                and r
                and isinstance(r[0], int)
                and r[0] > latest
                and (r[1] is not None or r[3] is not None)
            ):
                latest = r[0]
    for sym, qq in revop.items():
        for k in qq:
            try:
                q = int(k)
            except Exception:
                continue
            latest = max(latest, q)
    quarters = []
    q = latest
    for _ in range(N_Q):
        quarters.append(q)
        q = prev_qe(q)
    qidx = {q: i for i, q in enumerate(quarters)}
    print("quarters:", quarters[0], "..", quarters[-1])

    today = datetime.date.today()
    sr_cut = int((today - datetime.timedelta(days=SR_WINDOW_DAYS)).strftime("%Y%m%d"))

    out_co, n_rx, n_sr = {}, 0, 0
    syms = set(fund) | set(revop)
    for sym in sorted(syms):
        pdata = px.get(sym)
        meta = bmeta.get(sym) or {}
        if pdata is None or not meta.get("alive", True):
            continue
        d, c = pdata.get("d") or [], pdata.get("c") or []
        if len(d) != len(c) or not d:
            continue

        rows = [None] * N_Q
        anns = {}  # qe -> ann int (min of std/con)
        # PAT + ann dates from sf_fundamentals (owners basis)
        for r in fund.get(sym) or []:
            if not (isinstance(r, list) and len(r) >= 5 and isinstance(r[0], int)):
                continue
            i = qidx.get(r[0])
            if i is None:
                continue
            if rows[i] is None:
                rows[i] = [None] * 9
            if r[1] is not None:
                rows[i][2] = round(float(r[1]), 2)
            if r[3] is not None:
                rows[i][5] = round(float(r[3]), 2)
            ann = min([a for a in (r[2], r[4]) if a], default=None)
            # Impossible-pair belt (runbook §15): an ann on/before its own quarter-end can reach
            # this baker when a CI run's checkout predates a fill_ann_dates heal commit (ENRIN
            # 2026-07-21). Bake it as date-unknown instead of showing/using a date the result
            # cannot have; the source file is healed separately.
            if ann and ann <= r[0]:
                print("IMPOSSIBLE ann dropped: %s qe=%d ann=%d" % (sym, r[0], ann))
                ann = None
            if ann:
                anns[r[0]] = ann
                rows[i][6] = ann
        # Revenue / Operating Profit from sf_revop (pad legacy 7-elem)
        # fin (bank/NBFC/insurer FORMAT) comes from sf_revop's per-quarter flag, but the source flag
        # is a too-broad `"InterestEarned" in xml` substring that also fires on an INDUSTRIAL's
        # interest-on-cash — flipping Page Industries, Atul, Balrampur… to 'financial' off a single
        # stray fin=1 cell (audit 2026-09-01). Denoise CONSERVATIVELY: the company is financial if ANY
        # window quarter is fin (the source signal, which correctly reads 0 for fee-based financials
        # like CRISIL/CAMS/MCX), EXCEPT demote to industrial when the fin signal is a lone stray hit
        # (≤1 of ≥8 flagged quarters) AND the macro sector is not financial. That fixes the 18 clear
        # misflags and touches NOTHING ambiguous — real NBFCs with patchy tagging (PIRAMALFIN 4/12)
        # and every Financial-Services name stay exactly as before. (Majority voting would wrongly
        # demote those patchy NBFCs; sector alone would wrongly promote the fee-based financials.)
        fin_ones = fin_tot = 0
        for k, v in (revop.get(sym) or {}).items():
            try:
                qe = int(k)
            except Exception:
                continue
            i = qidx.get(qe)
            if i is None or not isinstance(v, list):
                continue
            v = v + [None] * (9 - len(v))
            if rows[i] is None:
                rows[i] = [None] * 9
            for src, dst in ((0, 0), (2, 1), (1, 3), (3, 4)):  # revS,opS,revC,opC
                if v[src] is not None:
                    with contextlib.suppress(Exception):
                        rows[i][dst] = round(float(v[src]), 2)
            if v[6] in (0, 1):
                fin_tot += 1
                fin_ones += 1 if v[6] == 1 else 0
        _kk = klass.get(sym) or klass.get(sym + ".NS") or {}
        _macro = _kk.get("macro") or (slim_meta.get(sym) or {}).get("sector") or meta.get("ind") or ""
        _fin_sector = "financial" in _macro.lower()
        fin = 1 if fin_ones >= 1 else 0
        if fin and fin_ones <= 1 and fin_tot >= 8 and not _fin_sector:
            fin = 0  # lone stray InterestEarned hit on a non-financial company
        if all(r is None for r in rows):
            continue

        # price reaction + drift
        for qe, ann in anns.items():
            i = qidx[qe]
            j = bisect_left(d, ann)
            if j <= 0 or j >= len(d):
                continue
            # reaction day must be within ~10 calendar days of ann (suspended names drop out)
            dd = datetime.date(d[j] // 10000, (d[j] // 100) % 100, d[j] % 100)
            ad = datetime.date(ann // 10000, (ann // 100) % 100, ann % 100)
            if (dd - ad).days > 10:
                continue
            if c[j - 1]:
                rows[i][7] = round((c[j] / c[j - 1] - 1) * 100, 2)
                n_rx += 1
            if ann >= sr_cut and c[j]:
                rows[i][8] = round((c[-1] / c[j] - 1) * 100, 1)
                n_sr += 1

        # cadence-predicted next result date
        e = 0
        reported = sorted(anns)
        if reported:
            pend = next_qe(reported[-1])
            lags = []
            same_month = (pend // 100) % 100
            for qe in reversed(reported[-8:]):
                lag = (qe_to_date(anns[qe]) - qe_to_date(qe)).days
                if 5 <= lag <= 100:
                    lags.append((0 if (qe // 100) % 100 == same_month else 1, lag))
            if lags:
                prim = [l for p, l in lags if p == 0] or [l for _, l in lags]
                pred = qe_to_date(pend) + datetime.timedelta(days=int(statistics.median(prim)))
                if pred >= today:
                    e = pred.isoformat()

        kk = klass.get(sym) or {}
        sme = slim_meta.get(sym) or {}
        sector = kk.get("macro") or sme.get("sector") or meta.get("ind") or "Others"
        if sector in ("Unknown", "Uncategorized", "Uncategorised", ""):
            sector = "Others"
        industry = kk.get("industry") or kk.get("igroup") or sme.get("industry") or ""
        out_co[sym] = {
            "n": sme.get("name") or meta.get("name") or sym,
            "s": sector,
            "i": industry,
            "m": round(float(sme.get("mcap") or 0), 1),
            "f": fin,
            "x": bits.get(sym, 0),
            "e": e,
            "q": rows,
        }

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    out = {"updated": ist.strftime("%Y-%m-%d %H:%M IST"), "asof": asof, "quarters": quarters, "co": out_co}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    mb = os.path.getsize(OUT) / 1e6
    n_lq = sum(1 for v in out_co.values() if v["q"][0] is not None)
    print(
        "WROTE %s: %d companies, %.1f MB (reactions %d, drift %d, latest-qtr reporters %d)"
        % (os.path.normpath(OUT), len(out_co), mb, n_rx, n_sr, n_lq)
    )


if __name__ == "__main__":
    main()
