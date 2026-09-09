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
"""Build the per-stock PRICE slices behind docs/stock.html's instant first paint.

WHY THIS EXISTS
  stock.html used to boot the whole backtest engine before it could draw a single
  company: stock_data.bin (17 MB) + the two sf-data halves (115 MB) +
  sf_fundamentals.json + shp_engine.json — ~137 MB of downloads and a ~250 MB
  JSON.parse, to show one page. Screener.in-class pages ship tens of KB. A slice
  carries EXACTLY what one stock's page reads, so the page opens in one request.

SHAPE
  The slice is written in the shape backtest-engine.js builds in memory, already
  normalised (exact x100 highs/lows, delivery % as a true percent), so the page
  installs it as a one-symbol SERIES/META/TURN and every math helper — hl52,
  rsi14, computeTech, retPctAt — runs against it unchanged. No parallel maths.

  sv    schema version (bump when the reader must change)
  sym / name / ind / alive / raw     header fields; raw = last UNADJUSTED close
  ts    START_TS the day offsets are measured from
  end   data end date (the page's "as of")
  d0/dd first day offset + per-bar gaps (delta-encoded: a long run of 1s and 3s
        gzips to almost nothing, where ascending absolute offsets do not)
  p     split/bonus-adjusted close x100, FULL history (the chart + every return)
  k     length of the tail arrays below
  h/l   exact intraday high/low x100  ] last k bars only: the deepest window any
  v     traded shares                 ] stat on the page looks back is 52 weeks,
  dv    delivery %                    ] so old bars would be dead weight
  t     turnover (₹ lacs)             ]
  mcap / mcapAt   market cap in ₹ cr and the close it was struck at (the page
        re-prices it off its own last close so a stale bake can't skew P/E)
  chips / fno     index memberships as of `end`, precomputed — this is the only
        reason the page ever pulled the 17 MB stock_data.bin

  sv=2 ACTIVITY + CONTEXT (2026-07-28) — everything below is per-stock rows cut
  from feeds the site already bakes, so the page never fetches a whole-market
  file. All are optional keys: absent = nothing on file, the page shows the
  section's empty state. Rolling windows are the feeds' own (ann 31 d, ins/dls
  ~92 d, act ≈ past 5 wk + upcoming), refreshed on this builder's daily cadence.
    act   [[date, kind D/B/S/O, purpose, exDate, value, yield%], …]   actions.json
    ann   [[ts, category, caption, pdfFile], …] newest first ≤30      announcements.json
    ins   [[date, person, cat, side, qty, ₹value, mode, %post], …] ≤30 insider.json
    dls   [[date, kind B/K, client, side, qty, price], …] ≤30         deals.json
    dsc   [[date, bucketTitle, blurb, pdfFile], …] ≤20                discovery.json
          (announcement-backed trigger buckets only — order wins, capacity, M&A…)
    strat [[strategyName, liveRet%, since, asOfDay], …] ≤12           live_tracking.json
          (tracked strategies whose CURRENT basket holds this stock, best return first)
    nr    'YYYY-MM-DD' next results date (earliest upcoming)          results_calendar.json
    rp    [ts, qEndYYYYMMDD, url] newest results-filing PDF (BSE)     results_feed.json
    peers {g: industry label, r: [[sym, name, mcap ₹cr, peTTM, r1y%], …]}
          same-industry peers by mcap (self first) — sector_classification.json
          `industry` level (igroup when thin); P/E from point-in-time owners PAT
          (last 4 CONTIGUOUS quarters), 1-y return from the price data

OUTPUT
  <outdir>/stk/<SLUG>.json  one per symbol (~8 KB average, 21 KB for a 30-year
  name) plus <outdir>/stk_meta.json carrying the data version, and
  <outdir>/pe_ttm.json — {sym: P/E TTM} for the whole market, read by
  docs/sectors.html's peer-comparison table.

  These are force-pushed to the sf-data Pages repo next to the split bins — every
  stock's slice changes every trading day, so committing them here would grow the
  repo by ~40 MB/day. Financials are NOT in here: they change on their own
  (results) cadence and live in docs/fin/ — see build_stock_fin.py.

  SLUG = symbol with anything outside [A-Za-z0-9._-] replaced by "_" (23 symbols
  carry & or +: M&M, L&T, SRERAYHY+H …). docs/stock.html applies the same rule.

Run: python scripts/build_stock_slices.py [--out DIR] [--only SYM,SYM]
"""
import argparse
import bisect
import gzip
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
# In CI the in-repo bin is the one update_sf_data.py just refreshed. Locally that copy
# can be weeks old, so SF_BIN=<path> lets you point at a freshly downloaded asset.
SF_BIN = os.environ.get("SF_BIN") or os.path.join(DOCS, "sf_stock_data.bin")
CORE_BIN = os.path.join(DOCS, "stock_data.bin")

TAIL = 400  # bars carrying h/l/v/dv/t — 52 weeks (~250 sessions) is the deepest window
SCHEMA = 2  # 2: activity feeds (act/ann/ins/dls/dsc/nr/rp) + peers — additive, sv=1 readers unaffected

ANN_CAP, INS_CAP, DLS_CAP, DSC_CAP = 30, 30, 30, 20
PEER_N = 8  # same-industry rows besides the stock itself

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")


def slug(sym):
    """Filename for a symbol. Mirrored by slugSym() in docs/stock.html."""
    return _UNSAFE.sub("_", sym)


def jload(path, what):
    """Optional feed: missing/corrupt file degrades that one section, never the build."""
    if not os.path.exists(path):
        print(f"WARN: {os.path.basename(path)} missing — {what} absent from slices")
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        print(f"WARN: {os.path.basename(path)} unreadable ({e}) — {what} absent from slices")
        return {}


def _trim(s, n):
    s = str(s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def build_activity(end):
    """Per-symbol rows cut from the whole-market activity feeds (see header)."""
    A = {}

    def add(kind, sym, row):
        A.setdefault(sym, {}).setdefault(kind, []).append(row)

    for r in jload(os.path.join(DOCS, "actions.json"), "corporate actions").get("rows") or ():
        # [date, sym, name, kind, purpose, exDate, value, yield]
        add("act", r[1], [r[0], r[3], _trim(r[4], 90), r[5], r[6], r[7]])
    for r in jload(os.path.join(DOCS, "announcements.json"), "announcements").get("rows") or ():
        # [sym, company, ts, category, caption, pdfFile]
        add("ann", r[0], [r[2], _trim(r[3], 60), _trim(r[4], 140), r[5]])
    for r in jload(os.path.join(DOCS, "insider.json"), "insider trades").get("rows") or ():
        # [date, sym, company, person, cat, side, qty, valueRs, mode, pctPost, key]
        add("ins", r[1], [r[0], _trim(r[3], 60), r[4], r[5], r[6], r[7], r[8], r[9]])
    for r in jload(os.path.join(DOCS, "deals.json"), "bulk/block deals").get("rows") or ():
        # [date, kind, sym, name, client, side, qty, price]
        add("dls", r[2], [r[0], r[1], _trim(r[4], 60), r[5], r[6], r[7]])
    for s in jload(os.path.join(DOCS, "live_tracking.json"), "strategy picks").get("strategies") or ():
        # a symbol sitting in a tracked strategy's CURRENT basket — [name, live ret %, since, as-of day]
        for p in (s.get("latest") or {}).get("picks") or ():
            if p.get("s"):
                add(
                    "strat",
                    p["s"],
                    [_trim(s.get("name"), 60), s.get("ret"), s.get("since"), (s.get("latest") or {}).get("day")],
                )
    for g in jload(os.path.join(DOCS, "discovery.json"), "discovery triggers").get("groups") or ():
        for b in g.get("buckets") or ():
            title = _trim(b.get("t"), 40)
            for r in b.get("rows") or ():
                # [sym, name, price, chg, date, blurb, pdfFile, value] — announcement-backed only.
                # Screen-type buckets reuse the row shape with numbers in these slots, so demand
                # a real ISO date AND a .pdf filename before treating it as a trigger event.
                if (
                    len(r) > 6
                    and isinstance(r[4], str)
                    and len(r[4]) == 10
                    and isinstance(r[6], str)
                    and r[6].lower().endswith(".pdf")
                ):
                    add("dsc", r[0], [r[4], title, _trim(r[5], 120), r[6]])

    caps = {"act": None, "ann": ANN_CAP, "ins": INS_CAP, "dls": DLS_CAP, "dsc": DSC_CAP, "strat": 12}
    for sym, d in A.items():
        for k, rows in d.items():
            if k == "dsc":  # one bucket can list a filing twice
                seen, out = set(), []
                for r in rows:
                    key = (r[0], r[2])
                    if key not in seen:
                        seen.add(key)
                        out.append(r)
                rows = out
            if k == "strat":  # best-performing strategies first, not date order
                rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))
            else:
                rows.sort(key=lambda r: r[0], reverse=True)
            if caps[k]:
                rows = rows[: caps[k]]
            d[k] = rows

    nr = {}
    for r in jload(os.path.join(DOCS, "results_calendar.json"), "results calendar").get("rows") or ():
        # [sym, name, date, purpose]
        if "result" in str(r[3] or "").lower() and r[2] >= end:
            if r[0] not in nr or r[2] < nr[r[0]]:
                nr[r[0]] = r[2]
    for sym, dt in nr.items():
        A.setdefault(sym, {})["nr"] = dt

    rp = {}
    for r in jload(os.path.join(DOCS, "results_feed.json"), "results filing PDFs").get("rows") or ():
        # [sym, name, ts, qEnd, caption, url]
        if r[0] not in rp or r[2] > rp[r[0]][0]:
            rp[r[0]] = [r[2], r[3], r[5]]
    for sym, row in rp.items():
        A.setdefault(sym, {})["rp"] = row

    return A


def _qi(qe):
    """Quarter index of a yyyymmdd quarter-end, for contiguity checks."""
    return (qe // 10000) * 4 + ((qe // 100) % 100 - 1) // 3


def fill_missing_mcaps(core, data):
    """Give the NSE-only cohort a market cap, in core_meta, before anything reads it.

    Every mcap in stock_data.bin traces to BSE's scrip master (fetch_all.py), which has no row
    for a company NSE lists and BSE doesn't — ~104 symbols (BSE Ltd, CDSL, E2E…) sit at mcap 0,
    which blanks Market cap AND P/E AND P/S AND P/B on the page and drops the stock to the
    bottom of its own peer table. scripts/shares_outstanding.json (from the SHP filings we
    already download) closes it: mcap = shares x last close, matching BSE's own figure to a
    median 0.08%.

    build_compressed.py does the same fill when it BUILDS the bin — but the committed
    docs/stock_data.bin is only ever patched in place (refresh-membership.yml, weekly) and its
    meta is months old, so relying on that alone would leave the page waiting indefinitely.
    Doing it here as well costs nothing and uses THIS build's close, which is today's.
    Fill-only: a real BSE mcap is never touched."""
    shares = jload(os.path.join(HERE, "shares_outstanding.json"), "NSE-only market caps")
    filled = 0
    for sym, rec in (shares or {}).items():
        n = (rec or [None])[0]
        if not n:
            continue
        key = sym + ".NS" if (sym + ".NS") in core else (sym if sym in core else sym + ".NS")
        cm = core.get(key)
        if cm and cm.get("mcap"):
            continue  # BSE already reported one
        closes = (data.get(sym) or {}).get("c") or ()
        if not closes or not closes[-1]:
            continue
        # update in place — the entry carries name/industry/52w fields other readers may want
        core.setdefault(key, {"symbol": sym}).update(
            {"mcap": round(n * closes[-1] / 1e7, 2), "latest": closes[-1], "mcapSrc": "shp:" + str(rec[1])}
        )
        filled += 1
    print("  mcap from SHP share counts: %d filled" % filled, flush=True)


def build_peer_stats(data, meta, core, end):
    """Per-symbol (mcap, P/E TTM, 1-y return) + industry buckets, for the peers table.
    P/E uses point-in-time owners PAT over the last 4 CONTIGUOUS quarters — same rule
    as the page's own TTM cards (a gap would understate the year and inflate P/E).
    Grouping uses sector_classification.json's `industry` level (191 groups — screener-like
    granularity: 'Refineries & Marketing', 'Private Sector Bank'), because the price bin's
    own `ind` has only ~22 coarse buckets that put RELIANCE next to COALINDIA. A thin
    industry (<3 peers) widens to its `igroup`."""
    fund = jload(os.path.join(DOCS, "sf_fundamentals.json"), "peer P/E")
    alias = jload(os.path.join(HERE, "_rename_map.json"), "peer renames")
    sclass = jload(os.path.join(DOCS, "sector_classification.json"), "peer industries")

    def pat_ttm(sym):
        f = fund.get(sym) or (fund.get(alias.get(sym)) if alias.get(sym) else None)
        if not f or len(f) < 4:
            return None
        rows = f[-4:]
        for i in range(1, 4):
            if _qi(rows[i][0]) != _qi(rows[i - 1][0]) + 1:
                return None
        tot = 0.0
        for r in rows:
            v = r[3] if r[3] is not None else r[1]
            if v is None:
                return None
            tot += v
        return tot

    try:
        e = end.replace("-", "")
        yago = int(e) - 10000
    except Exception:
        yago = None

    def group_of(sym):
        c = sclass.get(sym + ".NS") or sclass.get(sym) or {}
        fine = c.get("industry") or c.get("igroup")
        wide = c.get("igroup") or fine
        if not fine:
            m = meta.get(sym, {})
            fine = wide = m.get("ind") or m.get("industry")
        return fine, wide

    stats, by_fine, by_wide = {}, {}, {}
    for sym, o in data.items():
        m = meta.get(sym, {})
        cm = core.get(sym + ".NS") or core.get(sym) or {}
        mcap = cm.get("mcap")
        r1y = None
        d, c = o.get("d") or (), o.get("c") or ()
        if yago and len(c) > 1:
            j = bisect.bisect_right(d, yago) - 1
            if j >= 0 and c[j]:
                r1y = (c[-1] / c[j] - 1) * 100
        pe = None
        if mcap:
            pt = pat_ttm(sym)
            if pt and pt > 0:
                pe = mcap / pt
        stats[sym] = (mcap, pe, r1y)
        fine, wide = group_of(sym)
        if m.get("alive") and mcap:
            if fine:
                by_fine.setdefault(fine, []).append(sym)
            if wide:
                by_wide.setdefault(wide, []).append(sym)
    for grp in (by_fine, by_wide):
        for k in grp:
            grp[k].sort(key=lambda s: stats[s][0] or 0, reverse=True)
    return stats, (by_fine, by_wide, group_of)


def peers_for(sym, m, stats, groups, meta):
    by_fine, by_wide, group_of = groups
    fine, wide = group_of(sym)
    label, pool = fine, (by_fine.get(fine) or ())
    if len([x for x in pool if x != sym]) < 3 and wide and wide != fine:
        label, pool = wide, (by_wide.get(wide) or ())
    rows, rnd = [], lambda v, p: None if v is None else round(v, p)
    for s in [sym, *[x for x in pool if x != sym][:PEER_N]]:
        st = stats.get(s)
        if not st:
            continue
        nm = meta.get(s, {}).get("name") or s
        rows.append([s, _trim(nm, 28), (None if st[0] is None else round(st[0])), rnd(st[1], 1), rnd(st[2], 1)])
    return {"g": label, "r": rows} if len(rows) > 1 else None


def members_as_of(snaps, date_str):
    """Point-in-time membership: the newest snapshot effective on or before date_str
    (falling back to the oldest, as backtest-engine.js's lastSnap does)."""
    best = None
    for s in snaps or ():
        if s.get("effectiveDate", "") <= date_str and (best is None or s["effectiveDate"] > best["effectiveDate"]):
            best = s
    if best is None and snaps:
        best = snaps[0]
    return set(best.get("symbols") or ()) if best else set()


def build_slice(sym, o, m, end, ts, chips, fno, core):
    n = len(o["d"])
    k = min(TAIL, n)
    # Day offsets exactly as backtest-engine.js computes them (floor((utc - startTs)/DAY)),
    # then delta-encoded — a run of 1s and 3s gzips to nothing, absolute offsets do not.
    offs = [(_days(y) * 86400 - ts) // 86400 for y in o["d"]]
    p = [round(c * 100) for c in o["c"]]

    out = {
        "sv": SCHEMA,
        "sym": sym,
        "name": (m.get("name") or sym),
        "ind": (m.get("ind") or m.get("industry") or ""),
        "alive": 1 if m.get("alive") else 0,
        "raw": m.get("raw"),
        "ts": ts,
        "end": end,
        "d0": offs[0],
        "dd": [offs[i] - offs[i - 1] for i in range(1, n)],
        "p": p,
        "k": k,
    }

    # --- tail arrays: passed through VERBATIM ------------------------------------------------
    # The client applies the very same transform loadSF() does, so a slice cannot drift from the
    # whole-market path. Re-deriving values here instead cost real accuracy the first time round:
    # rounding turnover to an int put a 40% error on penny stocks (TVVISION 0.957 -> 0.571 ₹ lacs),
    # and converting the per-mil high/low into x100 paise moved 52-week lows on sub-₹10 names.
    if o.get("h") and o.get("l"):
        out["hl"] = 1  # exact intraday high/low…
        out["h"] = [round(x * 100) for x in o["h"][-k:]]  # …stored x100, as loadSF does
        out["l"] = [round(x * 100) for x in o["l"][-k:]]
    elif o.get("hb") and o.get("lb"):
        out["hb"] = o["hb"][-k:]  # legacy per-mil offsets from close
        out["lb"] = o["lb"][-k:]
    if o.get("v"):
        out["v"] = o["v"][-k:]
    if o.get("dv"):
        out["dv"] = o["dv"][-k:]  # x10 unless hl=1 — client divides
    if o.get("t"):
        out["t"] = [x or 0 for x in o["t"][-k:]]

    cm = core.get(sym + ".NS") or core.get(sym)
    if cm and cm.get("mcap"):
        out["mcap"] = round(cm["mcap"], 2)
        if cm.get("latest"):
            out["mcapAt"] = cm["latest"]
    if chips:
        out["chips"] = chips
    if fno:
        out["fno"] = 1
    return out


_EPOCH_CACHE = {}


def _days(yyyymmdd):
    """Days since the Unix epoch for a yyyymmdd int (cached — 5.9 M lookups)."""
    v = _EPOCH_CACHE.get(yyyymmdd)
    if v is None:
        import datetime

        y = int(yyyymmdd)
        v = (datetime.date(y // 10000, (y // 100) % 100, y % 100) - datetime.date(1970, 1, 1)).days
        _EPOCH_CACHE[yyyymmdd] = v
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=os.path.join(HERE, "_sfsplit"),
        help="directory to write stk/ into (default: the sf-data push staging dir)",
    )
    ap.add_argument("--only", default="", help="comma-separated symbols (debugging)")
    args = ap.parse_args()

    if not os.path.exists(SF_BIN):
        sys.exit(f"ABORT: {SF_BIN} missing — run scripts/update_sf_data.py first")

    print(f"reading {os.path.basename(SF_BIN)} …", flush=True)
    SF = json.loads(gzip.decompress(open(SF_BIN, "rb").read()))
    data, meta, end = SF["data"], SF.get("meta", {}), SF.get("end") or ""
    if len(data) < 3000:
        sys.exit("ABORT: sf payload has only %d symbols — refusing to publish truncated slices" % len(data))

    # stock_data.bin supplies the time base, index/F&O membership and market cap. Reading
    # it here is what lets the PAGE stop reading it: 17 MB of downloads become 3 fields.
    print("reading stock_data.bin …", flush=True)
    CORE = json.loads(gzip.decompress(open(CORE_BIN, "rb").read()))
    ts = CORE["startTs"]
    core_meta = CORE.get("meta", {})
    idx_hist = CORE.get("indicesHistory", {})
    fno_syms = members_as_of(CORE.get("fnoHistory", []), end)
    idx_mem = {name: members_as_of(snaps, end) for name, snaps in idx_hist.items()}
    print("  ts=%d  end=%s  indices=%d  fno=%d" % (ts, end, len(idx_mem), len(fno_syms)), flush=True)
    fill_missing_mcaps(core_meta, data)  # before peer stats AND slices — both read core_meta

    print("cutting activity feeds + peer stats …", flush=True)
    ACT = build_activity(end)
    pstats, groups = build_peer_stats(data, meta, core_meta, end)
    print("  activity for %d symbols, %d fine industries" % (len(ACT), len(groups[0])), flush=True)

    # Market-wide P/E, for the peer-comparison table in docs/sectors.html's index detail. It rides
    # THIS dict — the same point-in-time owners-PAT TTM the per-stock peers table uses — so there is
    # one P/E rule in the codebase, not two that drift. Only the RATIO travels: market cap and
    # returns are already on that page from dash_slim.bin, and two sources for one number is exactly
    # how two pages start quoting different market caps for the same company.
    pe_only = {s: round(v[1], 1) for s, v in pstats.items() if v[1] is not None}
    with open(os.path.join(args.out, "pe_ttm.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "end": end,
                "n": len(pe_only),
                "basis": "market cap / owners-attributable PAT, last 4 contiguous quarters as filed",
                "pe": pe_only,
            },
            fh,
            separators=(",", ":"),
        )
    print(
        "  pe_ttm.json: %d of %d symbols priced (rest have no contiguous TTM or no mcap)" % (len(pe_only), len(pstats)),
        flush=True,
    )

    outdir = os.path.join(args.out, "stk")
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)  # drop slices for symbols that vanished from the payload
    os.makedirs(outdir, exist_ok=True)

    only = {s.strip().upper() for s in args.only.split(",") if s.strip()}
    syms = sorted(s for s in data if not only or s in only)

    seen_slug, total, biggest = {}, 0, ("", 0)
    for i, sym in enumerate(syms):
        sl = slug(sym)
        if sl in seen_slug:
            sys.exit(f"ABORT: slug collision {sl!r}: {seen_slug[sl]} and {sym}")
        seen_slug[sl] = sym
        chips = sorted(name for name, mem in idx_mem.items() if sym in mem)
        payload = build_slice(sym, data[sym], meta.get(sym, {}), end, ts, chips, sym in fno_syms, core_meta)
        for k, v in (ACT.get(sym) or {}).items():  # act/ann/ins/dls/dsc lists + nr/rp scalars
            payload[k] = v
        pr = peers_for(sym, meta.get(sym, {}), pstats, groups, meta)
        if pr:
            payload["peers"] = pr  # {g: industry label, r: [[sym,name,mcap,pe,r1y], …] self first}
        blob = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        with open(os.path.join(outdir, sl + ".json"), "w", encoding="utf-8") as fh:
            fh.write(blob)
        total += len(blob.encode())
        if len(blob) > biggest[1]:
            biggest = (sym, len(blob))
        if i and i % 1000 == 0:
            print("  %d/%d" % (i, len(syms)), flush=True)

    with open(os.path.join(args.out, "stk_meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"end": end, "n": len(syms), "sv": SCHEMA}, fh, separators=(",", ":"))

    print(
        "stk slices: %d symbols, %.1f MB raw (avg %.1f KB), biggest %s %.0f KB, end=%s"
        % (len(syms), total / 1e6, total / len(syms) / 1024, biggest[0], biggest[1] / 1024, end)
    )


if __name__ == "__main__":
    main()
