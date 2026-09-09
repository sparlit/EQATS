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
"""DVL/DTIL wrong-company stitch repair (DATA_RUNBOOK §86-class, found by §88b 2026-08-11).

The NSE symbol DTIL was RECYCLED: Dhunseri Tea & Industries Ltd (the pre-2010 name of today's
Dhunseri Ventures, DVL) renamed DTIL->DPTL 2010-07-26, ->DPL 2014-11-12, ->DVL 2019-01-02; the
tea business demerged out in 2014 listed FRESH as DTIL on 2015-01-20 (ISIN INE341R01014, a
different company). build_sf_data.py's symchg.csv supplement has no recycled-ticker guard, so the
2026-08-02 full rebuild funneled ALL DTIL bhavcopy rows into DVL; the same-day dedup keeps the
lexicographically larger tuple (= higher close), so bin DVL 2015-01-20..2023-01-20 is a max-close
chimera of two companies (measured vs MTO volume identity: 2015-2020 ~100% tea-company bars,
2021-22 alternating, 2023+ DVL's own), and the tea company has no history at all (7-bar stub
created 2026-08-03 by the first post-rebuild daily run).

This script rebuilds both series from the official daily bhavcopies:
  fetch  — cache every day 2015-01-20 -> today via build_sf_data.fetch_day (resumable).
  build  — assemble scripts/dvl_dtil_surgery.json.gz:
             replace DVL [20150120..end] with DPL(->2018)/DVL(2019->) rows, RAW throughout —
             the "DVL 2021-08-05 Bonus 1:2" in NSE's own CA feed is MIS-KEYED: the drop is on
             DTIL's tape (521.15->346.65, x0.665), Yahoo has the 3:2 split on DTIL.NS and none
             on DVL, and DVL's equity capital is unchanged across 2021 (runbook §89e);
             create DTIL [20150120..end] from DTIL rows, x0.666667 before that bonus ex-date.
           Delivery %: bhavcopy DELIV_PER (2020+; BE/BZ '-' -> 100 per parse_rows) with MTO
           security-wise pct overlaid where dv==0 AND the MTO row's traded qty == bar volume
           (§88b volume-identity rule; MTO cache ~/.cache/mto_sweep).
           Validates volume identity vs MTO per year, join continuity, the bonus seam, equality
           with the live bin on the 2023+ overlap and the DTIL stub, and scans for unadjusted
           CA-like jumps, then writes the ledger only if every gate passes.
Applied nightly + idempotently by apply_series_surgery() in update_sf_data.py.
"""
import datetime
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_argv = sys.argv
sys.argv = _argv[:1]  # build_sf_data parses argv at import (dates)
sys.path.insert(0, HERE)
import contextlib

import build_sf_data as B  # noqa: E402

sys.argv = _argv

START = datetime.date(2015, 1, 20)  # new-DTIL listing day = first poisoned day
SYMS = ("DPL", "DVL", "DTIL")
BONUS_EX = 20210805  # DTIL (tea) 1:2 bonus — NSE feed mis-keys it as DVL
BONUS_F = 0.666667
MTO_DIR = os.path.expanduser("~/.cache/mto_sweep/mto")
S = os.environ.get("DVL_SCRATCH", HERE)


def days():
    d, today = START, datetime.date.today()
    while d <= today:
        yield d
        d += datetime.timedelta(days=1)


def fetch():
    j = B.jar()
    got = missing = 0
    for d in days():
        rows = B.fetch_day(d, j)
        if rows:
            got += 1
        else:
            missing += 1
        n = got + missing
        if n % 200 == 0:
            print("  %s  files=%d holidays/missing=%d" % (d, got, missing), flush=True)
    print("fetch done: %d trading-day files, %d empty" % (got, missing))


def mto_pct(ymd, sym, vol):
    """Delivery % from the day's MTO file, accepted only on exact traded==volume identity."""
    p = os.path.join(MTO_DIR, "%d.DAT" % ymd)
    if not os.path.exists(p):
        return 0
    for line in open(p, errors="replace"):
        f = line.strip().split(",")
        if len(f) >= 7 and f[0] == "20" and f[2].strip() == sym:
            try:
                t, pct = int(float(f[4])), float(f[6])
            except ValueError:
                continue
            if t == vol:
                return round(pct, 2)
    return 0


def build():
    j = B.jar()
    ser = {"DVL": [], "DTIL": []}  # bars: [ymd,c,t,h,l,op,v,dv,vw]
    multi = []
    prev_sig = None
    for d in days():
        rows = B.fetch_day(d, j)
        if not rows:
            continue
        # same duplicate-day guard as build_sf_data: NSE re-serves the prior trading day's file
        # on holidays/weekends — an exact duplicate would inject fake flat bars
        sig = hash(tuple((r[0], r[1]) for r in rows))
        if sig == prev_sig:
            continue
        prev_sig = sig
        ymd = int(d.strftime("%Y%m%d"))
        got = {}
        for r in rows:
            if r[0] in SYMS:
                if r[0] in got:
                    multi.append((ymd, r[0]))
                    continue  # first row wins; report
                got[r[0]] = r
        if "DPL" in got and "DVL" in got:
            raise SystemExit("ABORT %d: DPL and DVL both present — lineage assumption broken" % ymd)
        for tgt, r in (("DVL", got.get("DPL") or got.get("DVL")), ("DTIL", got.get("DTIL"))):
            if not r:
                continue
            sym, c, _p, t = r[0], r[1], r[2], r[3]
            h, l, o_, v = r[4], r[5], r[6], r[7]
            dlv, vw = r[8], r[9]
            # bar construction mirrors update_sf_data's day-append exactly
            hi = round(max(h, c), 2)
            lo_ = round(min(l, c) if l > 0 else c, 2)
            opx = round(o_, 2) if o_ > 0 else round(c, 2)
            vwx = round(vw, 2) if vw > 0 else round(c, 2)
            dvx = round(dlv, 2) if dlv else 0
            if not dvx:
                dvx = mto_pct(ymd, sym, int(v))
            # turnover in ₹ LACS — the bin-wide unit since §88a's normalization (2026-08-11).
            # Old-format files carry RUPEES; classify with §88a's own r = t/(c*v) test on RAW
            # values (rupee bar r ~ 1, lacs bar r ~ 1e-5, empty band between) and convert with
            # the same rounding normalize_turnover_units uses. Cannot rely on that pass to fix
            # spliced bars: it skips lacs-median days, and post-normalization every day is one.
            tv = round(t, 1)
            if v > 0 and c > 0 and tv / (c * v) > 0.01:
                nt = tv / 1e5
                tv = round(nt, 4) if nt < 100 else round(nt, 1)
            bar = [ymd, round(c, 2), tv, hi, lo_, opx, int(v), dvx, vwx]
            if tgt == "DTIL" and ymd < BONUS_EX:
                for i in (1, 3, 4, 5, 8):
                    bar[i] = round(bar[i] * BONUS_F, 2)
            ser[tgt].append(bar)
    if multi:
        print("NOTE: %d multi-series days (first row kept): %s" % (len(multi), multi[:10]))

    # ---- validation gates (all must pass before the ledger is written) ----
    bin_dump = json.load(open(os.path.join(S, "dvl_dtil.json")))
    fails = []

    # 1) MTO volume identity, per year per symbol
    def mto_traded(ymd, sym):
        p = os.path.join(MTO_DIR, "%d.DAT" % ymd)
        if not os.path.exists(p):
            return None
        tot = None
        for line in open(p, errors="replace"):
            f = line.strip().split(",")
            if len(f) >= 7 and f[0] == "20" and f[2].strip() == sym:
                with contextlib.suppress(ValueError):
                    tot = (tot or 0) + int(float(f[4]))
        return tot

    for tgt in ("DVL", "DTIL"):
        stat = {}
        for b in ser[tgt]:
            sym = tgt if not (tgt == "DVL" and b[0] < 20190101) else "DPL"
            t = mto_traded(b[0], sym)
            y = str(b[0])[:4]
            ok_, tot_ = stat.get(y, (0, 0))
            if t is not None:
                stat[y] = (ok_ + (1 if t == b[6] else 0), tot_ + 1)
        bad_years = {y: s for y, s in stat.items() if s[1] and s[0] / s[1] < 0.97}
        print(f"{tgt} volume identity vs MTO by year:", {y: "%d/%d" % s for y, s in sorted(stat.items())})
        if bad_years:
            fails.append(f"{tgt} volume identity <97% in {bad_years}")

    # 2) join continuity: kept pre-2015 bin bar (after prescale) -> first new DVL bar
    dvl_bin = bin_dump["DVL"]
    pos = {d: i for i, d in enumerate(dvl_bin["d"])}
    k_samples = []
    for ymd in (20080602, 20090601, 20101201, 20110601, 20120601, 20130603, 20140602, 20141215, 20150116, 20150119):
        d_ = datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100)
        rows = B.fetch_day(d_, B.jar()) or []
        raw = {r[0]: r[1] for r in rows}
        rc = raw.get("DTIL") if ymd < 20100801 else (raw.get("DPTL") or raw.get("DPL"))
        i = pos.get(ymd)
        if rc and i is not None:
            k_samples.append((rc, dvl_bin["c"][i]))
    k = sum(r * b for r, b in k_samples) / sum(r * r for r, b in k_samples)
    # correct DVL scale = RAW (its only official CA-feed factor is MIS-KEYED, §89e; the tape has
    # no CA-sized move anywhere 2015->date) -> the kept pre-2015 bars rescale by 1/k
    pre = round(1.0 / k, 6)
    anchor_c = dvl_bin["c"][pos[20150119]]
    join_ratio = ser["DVL"][0][1] / (anchor_c * pre)
    print(
        "pre-2015 scale k=%.6f (n=%d)  pre=%.6f  join 20150119->20150120 ratio=%.4f"
        % (k, len(k_samples), pre, join_ratio)
    )
    if not (0.93 <= join_ratio <= 1.07):
        fails.append(f"join ratio {join_ratio:.4f} out of band")

    # 3) DTIL bonus seam on the constructed (adjusted) series
    dt_bars = ser["DTIL"]
    si = next(i for i, b in enumerate(dt_bars) if b[0] >= BONUS_EX)
    seam = dt_bars[si][1] / dt_bars[si - 1][1]
    print("DTIL bonus seam %d->%d adjusted ratio=%.4f" % (dt_bars[si - 1][0], dt_bars[si][0], seam))
    if not (0.75 <= seam <= 1.30):
        fails.append(f"DTIL bonus seam ratio {seam:.4f} out of band")

    # 4) overlap equality vs live bin where the bin is already the right company
    def overlap(tgt, frm):
        e = bin_dump[tgt]
        p2 = {d: i for i, d in enumerate(e["d"])}
        eq = tot = 0
        diffs = []
        for b in ser[tgt]:
            if b[0] < frm:
                continue
            i = p2.get(b[0])
            if i is None:
                continue
            tot += 1
            cur = [e["d"][i], e["c"][i], e["t"][i], e["h"][i], e["l"][i], e["op"][i], e["v"][i], e["dv"][i], e["vw"][i]]
            if cur == b:
                eq += 1
            elif len(diffs) < 5:
                diffs.append((b[0], cur, b))
        return eq, tot, diffs

    eq, tot, diffs = overlap("DVL", 20230123)
    print("DVL 2023+ overlap: %d/%d bars byte-equal" % (eq, tot))
    if tot and eq / tot < 0.98:
        fails.append("DVL 2023+ overlap only %d/%d equal; e.g. %s" % (eq, tot, diffs))
    eq2, tot2, diffs2 = overlap("DTIL", 20260803)
    print("DTIL stub overlap: %d/%d bars byte-equal" % (eq2, tot2))
    if tot2 and eq2 / tot2 < 0.99:
        fails.append("DTIL stub mismatch %d/%d; %s" % (eq2, tot2, diffs2))

    # 5) unadjusted CA-jump scan on raw closes (only DTIL's 2021 bonus may appear, on DTIL)
    for tgt in ("DVL", "DTIL"):
        hits = []
        rc_prev = None
        for b in ser[tgt]:
            rc = b[1] / (BONUS_F if (tgt == "DTIL" and b[0] < BONUS_EX) else 1.0)
            if rc_prev and not (0.75 <= rc / rc_prev <= 1.30):
                if not (tgt == "DTIL" and b[0] == BONUS_EX):
                    hits.append((b[0], round(rc / rc_prev, 3)))
            rc_prev = rc
        print("{} raw CA-like jumps (excl. DTIL's official bonus): {}".format(tgt, hits or "none"))
        if hits:
            fails.append(f"{tgt} unexplained CA-like jumps: {hits}")

    if fails:
        raise SystemExit("VALIDATION FAILED — ledger NOT written:\n  " + "\n  ".join(map(str, fails)))

    out = {
        "built": datetime.date.today().isoformat(),
        "note": "DVL/DTIL recycled-ticker stitch repair — DATA_RUNBOOK §89 (DTIL 2015+ is a "
        "different company than the DTIL->DPTL->DPL->DVL chain)",
        "replace": {
            "DVL": {"from": 20150120, "bars": ser["DVL"], "pre": pre, "pre_anchor": {"ymd": 20150119, "c": anchor_c}}
        },
        "create": {
            "DTIL": {
                "bars": ser["DTIL"],
                "meta": {
                    "name": "Dhunseri Tea & Industries Ltd",
                    "ind": "Fast Moving Consumer Goods",
                    "isin": "INE341R01014",
                    "alive": True,
                },
            }
        },
    }
    path = os.path.join(HERE, "dvl_dtil_surgery.json.gz")
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(
        "wrote %s  DVL bars=%d (%d..%d) pre=%.6f  DTIL bars=%d (%d..%d)"
        % (
            path,
            len(ser["DVL"]),
            ser["DVL"][0][0],
            ser["DVL"][-1][0],
            pre,
            len(ser["DTIL"]),
            ser["DTIL"][0][0],
            ser["DTIL"][-1][0],
        )
    )


if __name__ == "__main__":
    {"fetch": fetch, "build": build}[sys.argv[1] if len(sys.argv) > 1 else "fetch"]()
