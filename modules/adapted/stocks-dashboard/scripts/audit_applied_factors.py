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
"""Recover EVERY split/bonus factor baked into the published price bins and check each against the
official records (DATA_RUNBOOK §161e). Read-only: writes a report, never touches a ledger or a bin.

Why it works: update_sf_data / build_sf_data rescale close/high/low/open/VWAP on an adjustment but
NEVER the traded turnover (t, Rs lakh) or volume (v, shares). So per bar the raw VWAP is t*1e5/v and
    cum = vw_adjusted / (t*1e5/v)
is the product of every factor applied AFTER that bar. A persistent level shift in `cum` across a
boundary is exactly the factor divided out there (RELIANCE's 1997/2009/2017/2024 bonuses and its
2006/2023 demergers come back exact).

Kept: shifts within 1.5% of a canonical CA fraction whose implied RAW move lies outside [0.75,1.30]
(the only moves ca_factor() inference ever touched) with both closes >= 0.25 (self_heal's precision
floor). Each is classified against corp_actions(+hist) / demerger_adj / rights_terp /
ca_open_arbitrated / MANUAL_RIGHTS / phantom_crashes / LEGACY_FALSE_CA, then — for events with no
record — against Yahoo's split-adjusted closes (docs/stock_data.bin) as an independent second reader
and the §87c ex-day open gate. Evidence columns only; verdicts stay with a human (§0 no assumptions).

--tape (§161j, the exact witness — use it): per bar, stored close / NSE's RAW close (scripts/_raw_tape/, cached
by fetch_raw_tape.py from the bhavcopies, 2002+) IS the applied-factor product, to 2-decimal rounding. Runs of
bars that share one scale are found by interval intersection; every boundary between runs is an applied factor,
of ANY size, at ANY price (no Rs0.25 floor — tick-limited ones are flagged) and at ANY spacing. The turnover
witness covered only the inference domain, lost thin/penny names to turnover rounding (t is kept to 0.1 lakh)
and blurred factors one bar apart (NATNLSTEEL 2020, §165f). A one-bar run whose neighbours share a scale is a
BAR MISMATCH (reported separately), not a factor pair. Boundaries the tape cannot reach (pre-2002, no bhavcopy
row) fall back to the turnover witness, whose windows are now bounded at neighbouring factor-sized boundaries.

Run:  python3 scripts/audit_applied_factors.py <dir with sf_deep_*.bin + sf_recent_*.bin> [out.json] [--tape]
      (the bins are the sf-data Pages repo: git clone --depth 1 https://github.com/dhruvan246/sf-data)
"""
import ast
import bisect
import collections
import datetime
import glob
import gzip
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CA = [
    1 / 2,
    1 / 3,
    2 / 3,
    1 / 4,
    3 / 4,
    1 / 5,
    2 / 5,
    3 / 5,
    1 / 6,
    5 / 6,
    1 / 8,
    1 / 10,
    1 / 20,
    1 / 50,
    2.0,
    3.0,
    4.0,
    5.0,
    10.0,
]
WIN = 4  # bars either side for the level-shift median
PX_FLOOR = 0.25  # same floor as update_sf_data.self_heal


def od(y):
    return datetime.date(y // 10000, y // 100 % 100, y % 100)


def load_bins(d):
    ser = {}
    files = sorted(glob.glob(os.path.join(d, "sf_deep_*.bin"))) + sorted(glob.glob(os.path.join(d, "sf_recent_*.bin")))
    if not files:
        sys.exit(f"no sf_deep_*/sf_recent_* bins in {d}")
    for f in files:
        D = json.loads(gzip.open(f).read())
        for s, o in D["data"].items():
            e = ser.setdefault(s, {})
            for i, x in enumerate(o["d"]):
                e[x] = (
                    o["c"][i],
                    o["t"][i],
                    o["v"][i],
                    (o.get("vw") or [None] * len(o["d"]))[i],
                    (o.get("op") or [None] * len(o["d"]))[i],
                )
        print("loaded %s (%d symbols)" % (os.path.basename(f), len(D["data"])), flush=True)
    return ser


def applied_events(ser, only=None):
    """The turnover witness (cum = vw / (t*1e5/v)). `only(sym, a, b)` -> False drops a boundary the
    --tape witness already measured exactly.
    §161j: a boundary is ALSO tested with windows BOUNDED at the neighbouring factor-sized boundaries (single-bar
    |log f| >= log 1.25). Unbounded, two factors one bar apart shared one window and blurred into a
    fraction matching neither (NATNLSTEEL 2020-04-13 x1/2 + 2020-07-13 x3 read 1.67 / 1.80 — §165f). An event
    found by either window rule is kept (the union), tagged `window` = unbounded / bounded / both."""
    out = []
    for s, e in ser.items():
        cum = []
        for x in sorted(e):
            c, t, v, vw, _ = e[x]
            if t and v and vw and t > 0 and v > 0 and vw > 0:
                cum.append((x, vw / (t * 1e5 / v), c))
        big = [
            i
            for i in range(len(cum) - 1)
            if cum[i + 1][1] and abs(__import__("math").log(cum[i][1] / cum[i + 1][1])) >= 0.2231
        ]
        for i in range(len(cum) - 1):
            a, b = cum[i][1], cum[i + 1][1]
            f = a / b if b else 1
            if abs(f - 1) <= 0.03 or not (1e-3 < f < 1e3):
                continue
            if only is not None and not only(s, cum[i][0], cum[i + 1][0]):
                continue
            k = bisect.bisect_left(big, i)  # big[k-1] < i <= big[k]
            lo = big[k - 1] + 1 if k > 0 else 0  # first bar after the previous boundary
            k2 = bisect.bisect_right(big, i)  # first boundary strictly after i
            hi = big[k2] + 1 if k2 < len(big) else len(cum)  # post window stops at the next boundary
            found = []
            for how, (p0, p1) in (("unbounded", (0, len(cum))), ("bounded", (lo, hi))):
                pre = [y[1] for y in cum[max(p0, i - WIN + 1) : i + 1]]
                post = [y[1] for y in cum[i + 1 : min(p1, i + 1 + WIN)]]
                if not pre or not post:
                    continue
                if (len(pre) < 2 or len(post) < 2) and how == "unbounded" and i + 1 != len(cum) - 1:
                    continue
                Fh = statistics.median(pre) / statistics.median(post)
                if any(abs(Fh / q - 1) <= 0.015 for q in CA) and abs(Fh / f - 1) < 0.05:
                    found.append((how, Fh))
            if not found:
                continue
            F = found[0][1]
            ca, cb = cum[i][2], cum[i + 1][2]
            if not ca or min(ca, cb) < PX_FLOOR:
                continue
            raw = F * cb / ca
            if 0.75 <= raw <= 1.30:
                continue
            out.append(
                {
                    "sym": s,
                    "a": cum[i][0],
                    "b": cum[i + 1][0],
                    "F": round(F, 4),
                    "raw": round(raw, 4),
                    "adj_a": ca,
                    "adj_b": cb,
                    "open_b": e[cum[i + 1][0]][4],
                    "witness": "turnover",
                    "window": "both" if len(found) == 2 else found[0][0],
                }
            )
    return out


# ---------------------------------------------------------------- §161j: the EXACT witness
# stored(t) = raw(t) x PROD{factors applied after t}, so stored/raw per bar IS the applied product, known to
# 2-decimal rounding. Raw closes = NSE's own bhavcopies (scripts/_raw_tape/, fetch_raw_tape.py). A run of bars
# whose scale intervals [(c-h)/r, (c+h)/r] share a point sits on ONE scale; where no point fits, a factor was
# applied between the two bars. Exact at any price (CCCL's Rs0.20 ticks) and at any spacing (NATNLSTEEL's
# factors one bar apart), with no turnover noise.
TAPE = os.path.join(HERE, "_raw_tape")
EQ_SERIES = ("EQ", "BE", "BZ", "SM", "ST", "SZ")  # priority order for a symbol printed in more than one series


def _merge_aliases():
    """current key -> [printed names that key's history was ingested under], most recent rename first."""
    rm = json.load(open(os.path.join(HERE, "_rename_map.json")))  # era -> current
    src = open(os.path.join(HERE, "update_sf_data.py")).read()
    blk = src[src.index("MANUAL_MERGE = {") : src.index("MANUAL_MERGE.update(SEAM_MERGES)")]
    pairs = [(n, o) for n, o in re.findall(r'"([A-Z0-9&\-]+)":\s*"([A-Z0-9&\-]+)"', blk)]
    pairs += [(n, o) for n, o in re.findall(r'"([A-Z0-9&\-]+)":\s*\{"old":\s*"([A-Z0-9&\-]+)"', blk)]
    al = collections.defaultdict(list)
    for o, n in rm.items():
        if o != n:
            al[n].append(o)
    for n, o in pairs:
        if o != n and o not in al[n]:
            al[n].append(o)
    for _ in range(4):  # transitive: A -> B -> C
        for n in list(al):
            for o in list(al[n]):
                for oo in al.get(o, []):
                    if oo != n and oo not in al[n]:
                        al[n].append(oo)
    return al


def load_tape(names):
    """-> {printed_symbol: {ymd: (close, prev_close, open)}} for the requested printed names only."""
    from array import array

    tape = {}
    files = sorted(f for f in os.listdir(TAPE) if f.endswith(".json.gz"))
    for k, f in enumerate(files):
        D = json.load(gzip.open(os.path.join(TAPE, f)))
        y = D["date"]
        for sym, rows in D["rows"].items():
            if sym not in names:
                continue
            rows = [r for r in rows if r[0] in EQ_SERIES]
            if not rows:
                continue
            r = min(rows, key=lambda r: EQ_SERIES.index(r[0]))
            t = tape.get(sym)
            if t is None:
                t = tape[sym] = (array("i"), array("d"), array("d"), array("d"))
            t[0].append(y)
            t[1].append(r[1])
            t[2].append(r[2])
            t[3].append(r[3])
        if k % 1000 == 0:
            print("  tape %d/%d files" % (k, len(files)), flush=True)
    return {s: {t[0][i]: (t[1][i], t[2][i], t[3][i]) for i in range(len(t[0]))} for s, t in tape.items()}, files


def applied_events_tape(ser, tape, alias):
    out, blips, covered = [], [], set()
    for s, e in ser.items():
        names = [s, *alias.get(s, [])]
        bars = []
        for y in sorted(e):
            c = e[y][0]
            if not c or c <= 0:
                continue
            for nm in names:
                r = (tape.get(nm) or {}).get(y)
                if r and r[0] > 0:
                    bars.append((y, c, r[0], r[1], r[2], nm))
                    break
        if len(bars) < 2:
            continue
        covered.add((s, bars[0][0], bars[-1][0]))  # the span the exact witness reaches for this symbol
        # greedy single-scale runs
        segs = []
        for k, (y, c, r, *_rest) in enumerate(bars):
            h = 0.011 + 0.001 * c
            L, H = max(c - h, 1e-6) / r, (c + h) / r  # a Rs0.01 close: lower bound clamps at ~0
            if segs and max(segs[-1][2], L) <= min(segs[-1][3], H):
                sg = segs[-1]
                sg[1] = k
                sg[2] = max(sg[2], L)
                sg[3] = min(sg[3], H)
            else:
                segs.append([k, k, L, H])
        # a ONE-bar run whose neighbours share a scale is a bad bar, not a factor pair -> report, merge
        changed = True
        while changed:
            changed = False
            for q in range(1, len(segs) - 1):
                a_, m_, b_ = segs[q - 1], segs[q], segs[q + 1]
                if m_[0] == m_[1] and max(a_[2], b_[2]) <= min(a_[3], b_[3]):
                    y, c, r = bars[m_[0]][:3]
                    blips.append(
                        {
                            "sym": s,
                            "d": y,
                            "stored": c,
                            "raw": r,
                            "scale": round(c / r, 4),
                            "run_scale": round((max(a_[2], b_[2]) * min(a_[3], b_[3])) ** 0.5, 4),
                            "via": bars[m_[0]][5],
                        }
                    )
                    segs[q - 1 : q + 2] = [[a_[0], b_[1], max(a_[2], b_[2]), min(a_[3], b_[3])]]
                    changed = True
                    break
        for q in range(len(segs) - 1):
            A, Bq = segs[q], segs[q + 1]
            i, j = A[1], Bq[0]
            lo_F, hi_F = A[2] / Bq[3], A[3] / Bq[2]  # every factor consistent with both runs
            if hi_F >= 0.985 and lo_F <= 1.015:
                continue  # indistinguishable from 1 at 2dp
            sa, sb = (A[2] * A[3]) ** 0.5, (Bq[2] * Bq[3]) ** 0.5
            F = sa / sb
            (ya, ca, ra, _pa, _oa, na), (yb, cb, rb, pb, ob, nb) = bars[i], bars[j]
            out.append(
                {
                    "sym": s,
                    "a": ya,
                    "b": yb,
                    "F": round(F, 4),
                    "F_range": [round(lo_F, 4), round(hi_F, 4)],
                    "raw": round(rb / ra, 4),
                    "raw_a": ra,
                    "raw_b": rb,
                    "prevclose_b": pb,
                    "rawopen_b": ob,
                    "adj_a": ca,
                    "adj_b": cb,
                    "open_b": e[yb][4],
                    "scale_a": round(sa, 4),
                    "scale_b": round(sb, 4),
                    "run_a": A[1] - A[0] + 1,
                    "run_b": Bq[1] - Bq[0] + 1,
                    "tick_limited": (hi_F / lo_F) > 1.05,
                    "via": [na, nb] if na != s or nb != s else None,
                    "witness": "tape",
                }
            )
    return out, blips, covered


def ledgers():
    off = collections.defaultdict(list)
    noa = collections.defaultdict(set)
    for f in ("corp_actions.json", "corp_actions_hist.json"):
        C = json.load(open(os.path.join(HERE, f)))
        for s, v in C.get("factors", {}).items():
            for x in v:
                off[s].append((int(x[0]), float(x[1])))
        for s, v in C.get("noadjust", {}).items():
            for x in v:
                noa[s].add(int(x))
    led = collections.defaultdict(set)
    for x in json.load(open(os.path.join(HERE, "demerger_adj.json"))):
        led[x[0]].add(("demerger_adj", int(x[1])))
    for x in json.load(open(os.path.join(HERE, "rights_terp.json"))):
        led[x[0]].add(("rights_terp", int(x[1])))
    for x in json.load(open(os.path.join(HERE, "ca_open_arbitrated.json")))["events"]:
        led[x[0]].add(("ca_open_arbitrated", int(x[1])))
    src = open(os.path.join(HERE, "update_sf_data.py")).read()
    m = re.search(r"MANUAL_RIGHTS = (\[.*?\n\])", src, re.DOTALL)
    for t in ast.literal_eval(re.sub(r"#.*", "", m.group(1))):
        led[t[0]].add(("MANUAL_RIGHTS", int(t[1])))
    pc = collections.defaultdict(set)
    for s, v in json.load(open(os.path.join(HERE, "phantom_crashes.json"))).items():
        for x in v:
            pc[s].add(int(x))
    m = re.search(r"LEGACY_FALSE_CA = (\[.*?\n\])", src, re.DOTALL)
    for s, x in ast.literal_eval(re.sub(r"#.*", "", m.group(1))):
        pc[s].add(x)
    return off, noa, led, pc


def yahoo():
    Y = json.loads(gzip.open(os.path.join(ROOT, "docs", "stock_data.bin")).read())
    ts = Y["startTs"]
    out = {}
    for k, s in Y["series"].items():
        if k.endswith(".NS"):
            out[k[:-3]] = (
                [int(datetime.datetime.utcfromtimestamp(ts + o * 86400).strftime("%Y%m%d")) for o in s["d"]],
                [p / 100 for p in s["p"]],
            )
    return out


def classify(ev, off, noa, led, pc, Y):
    def near(d, a, b, pad=7):
        return od(a) - datetime.timedelta(days=pad) <= od(d) <= od(b) + datetime.timedelta(days=pad)

    for r in ev:
        s, a, b = r["sym"], r["a"], r["b"]
        r["official"] = sorted({x for x in off[s] if near(x[0], a, b)})  # corp_actions + hist list the same row twice
        r["noadjust"] = sorted(x for x in noa[s] if near(x, a, b))
        r["ledger"] = sorted(x for x in led[s] if near(x[1], a, b))
        r["crash_listed"] = sorted(x for x in pc[s] if near(x, a, b))
        cls = (
            "OFFICIAL"
            if r["official"]
            else "LEDGER"
            if r["ledger"]
            else "CRASH_LISTED_STILL_ADJUSTED"
            if r["crash_listed"]
            else "DEMERGER_BUT_ADJUSTED"
            if r["noadjust"]
            else "NO_RECORD"
        )
        if cls == "OFFICIAL" and r.get("witness") == "tape":
            po = 1.0
            for _, f in r["official"]:
                po *= f
            lo, hi = r["F_range"]
            if not (lo * 0.98 <= po <= hi * 1.02):
                cls = "OFFICIAL_VALUE_MISMATCH"
                r["official_product"] = round(po, 6)
        if cls == "NO_RECORD" and r.get("via") and r["via"][0] != r["via"][1]:
            cls = "TICKER_SEAM"
        r["class"] = cls
        r["in_inference_domain"] = not (0.75 <= r["raw"] <= 1.30)
        # §87c open gate on the drop bar: (raw open / raw prev) / F
        r["open_gate"] = round((r["open_b"] / r["adj_a"]), 4) if r.get("open_b") and r["adj_a"] else None
        y = Y.get(s)
        if not y:
            r["yahoo"] = "no-series"
            continue
        d, p = y
        i = bisect.bisect_right(d, a) - 1
        j = bisect.bisect_left(d, b)
        if i < 0 or j >= len(d) or not p[i] or not p[j]:
            r["yahoo"] = "no-bar"
            continue
        ry = p[j] / p[i]
        r["yahoo_ratio"] = round(ry, 4)
        r["yahoo"] = (
            "shows-raw-move"
            if abs(ry / r["raw"] - 1) <= 0.12
            else "agrees-with-adjustment"
            if abs(ry / (r["adj_b"] / r["adj_a"]) - 1) <= 0.12
            else "neither"
        )
    return ev


def main():
    args = [x for x in sys.argv[1:] if not x.startswith("--")]
    if not args:
        sys.exit(__doc__)
    use_tape = "--tape" in sys.argv
    outp = (
        args[1]
        if len(args) > 1
        else os.path.join(HERE, "_audit_applied_factors%s.json" % ("_tape" if use_tape else ""))
    )
    ser = load_bins(args[0])
    blips, tape_files = [], []
    if use_tape:
        alias = _merge_aliases()
        names = set(ser) | {o for s in ser for o in alias.get(s, [])}
        tape, tape_files = load_tape(names)
        ev, blips, covered = applied_events_tape(ser, tape, alias)
        span = {}
        for s, a, b in covered:
            lo, hi = span.get(s, (a, b))
            span[s] = (min(lo, a), max(hi, b))

        def inside(s, a, b):
            return s in span and span[s][0] <= a and b <= span[s][1]

        ev += applied_events(ser, only=lambda s, a, b: not inside(s, a, b))  # turnover witness where no tape reaches
    else:
        ev = applied_events(ser)
    off, noa, led, pc = ledgers()
    Y = yahoo()
    classify(ev, off, noa, led, pc, Y)
    meta = {
        "generated": datetime.datetime.utcnow().isoformat() + "Z",
        "bins": os.path.abspath(args[0]),
        "tape_sessions": len(tape_files),
        "tape_first": tape_files[0][:8] if tape_files else None,
        "tape_last": tape_files[-1][:8] if tape_files else None,
    }
    json.dump(dict(meta, events=ev, bar_mismatches=blips), open(outp, "w"), indent=0)
    c = collections.Counter((r.get("witness"), r["class"], r["in_inference_domain"]) for r in ev)
    print(
        "%d applied factors (tape = exact, all sizes; turnover = inference domain only); by (witness, class, raw outside [0.75,1.30]):"
        % len(ev)
    )
    for k, v in sorted(c.items(), key=lambda x: -x[1]):
        print("  %5d  %s" % (v, k))
    if use_tape:
        print("bar mismatches (one bar off its neighbours' common scale): %d" % len(blips))
    print(f"report -> {outp}")


if __name__ == "__main__":
    main()
