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
"""
INDEX SURVIVORSHIP TABLE -- one row per stock that was EVER a member of a Nifty index: the
survivors AND every name that left (dropped, merged, delisted), with the dates, prices and
returns of each membership stint. Consumed by docs/index-chart.html ("Every member, ever" card,
lazy-loaded, one file per index) -- the page never loads a price bin.

Output: docs/survivorship/<slug>.json (minified)
  { "index":"Nifty 500", "slug":"nifty500", "updated":"YYYY-MM-DD", "dataEnd":"YYYY-MM-DD",
    "snaps":339, "firstSnap":"1998-08-01", "lastSnap":"2026-09-30", "rosterAsOf":"2026-03-30",
    "upcoming":"2026-09-30"|null, "nIn":501, "nOut":..., "nDead":..., "nUntraced":...,
    "idxSeries":"where the index level came from", "cols":[...], "rows":[[...], ...] }

  Row fields (in `cols` order):
    sym       bin key the roster name resolved to (the CURRENT ticker after rename folds); a
              roster name with no price series keeps its own name and status "untraced"
    name, sector, industry, isin, mcap (Rs Cr, today)   -- from the sf bin meta / dash_slim meta
    status    in        = in the roster in force on dataEnd
              out       = left the index, still trades
              dead      = left the index and no longer trades (delisted / merged / suspended)
              untraced  = no price series under this or any renamed key (old pre-2004 names)
    first     first join date (effectiveDate of the first snapshot that carries it)
    fromStart true when the name is in the very FIRST snapshot -- it was ALREADY a member when the
              record begins, so `first` is a floor on the real join date, not the join itself
    last      date it last LEFT (effectiveDate of the first snapshot without it), null while in
    n         number of separate membership stints
    days      calendar days as a member, all stints summed (an open stint runs to dataEnd)
    joinPx    adjusted close on the first bar on/after the first join (within 45 days, else null)
    exitPx    adjusted close on the last bar BEFORE the latest exit (null while in)
    lastPx    the series' last close;  lastD = its date (a dead name stops early)
    retIn     % return over the membership stints, compounded (open stint valued at lastPx)
    cagrIn    retIn annualised over `days` (null under 1 year)
    retSince  % from joinPx to lastPx -- what buying at the first inclusion did
    retAfter  % from exitPx to lastPx -- what happened AFTER it was dropped (null while in)
    idxIn     % the index itself did over the same stint windows, compounded (null when the
              index level is unknown for a window)
    relIn     (1+retIn)/(1+idxIn)-1: the member vs the index while it was a member
    maxDD     worst peak-to-trough fall (%) on closes WHILE a member, across stints
    upcoming  "join YYYY-MM-DD" / "leave YYYY-MM-DD" when an announced reshuffle dated after
              dataEnd changes it (the FUTURE-dated snapshot -- announced, not yet in force)
    st        the stints: [[join, leave|null, joinPx, exitPx, ret%], ...] oldest first

METHOD / CONVENTIONS (each measured against the sibling builders, 2026-09-21)
  - Prices: docs/sf_stock_data.bin -- the LIVE rebuild (scripts/fetch_live_sf.py) or the `data`
    release asset in CI; never the frozen committed copy (runbook section 0). Closes are the bin's
    corp-action-adjusted `c`; non-positive closes (the zero-close penny defect) are skipped.
    Bars before `dailyFrom` (2002-01-02) are weekly samples -- a 45-day window absorbs that.
  - Membership: docs/dash_slim.bin indicesHistory[<name>], the SAME event-driven snapshots the
    backtest engine's membersAsOf() reads. A stint opens at the effectiveDate of the first
    snapshot carrying the name and closes at the effectiveDate of the first later snapshot
    without it. DUMMY* placeholders are dropped; DVR lines are KEPT (a listed security that was
    officially in the index is a row here, unlike the breadth builders which count companies).
  - Rename fold (engine rule): a roster name that IS a bin key is used as-is; otherwise it is
    folded through scripts/_rename_map.json chained to its end. Two roster names folding to one
    series become ONE row (their stints merged in date order).
  - Index level for idxIn: the per-index daily-close JSON (docs/nifty500.json ...) where it
    exists, and docs/index_monthly.json month-end closes before that. A window whose start or
    end has no level within 45 days yields null -- never a guess.
  - Roster in force = latest snapshot with effectiveDate <= dataEnd. A later-dated snapshot is
    an ANNOUNCED reshuffle: its joins/leaves are reported in `upcoming`, not applied to status.

Run:  python3 -X utf8 scripts/build_index_survivorship.py            # default: nifty500
      python3 -X utf8 scripts/build_index_survivorship.py all        # every index in INDEXES
      python3 -X utf8 scripts/build_index_survivorship.py nifty50 niftybank
      SF_BIN=/path/fresh.bin DASH_SLIM=/path/dash_slim.bin python3 -X utf8 scripts/build_index_survivorship.py
"""
import gzip
import json
import os
import sys
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.environ.get("SF_BIN") or os.path.join(ROOT, "docs", "sf_stock_data.bin")
SLIM = os.environ.get("DASH_SLIM") or os.path.join(ROOT, "docs", "dash_slim.bin")
RMAP = os.path.join(HERE, "_rename_map.json")
SECT = os.path.join(ROOT, "docs", "sector_classification.json")
MONTHLY = os.path.join(ROOT, "docs", "index_monthly.json")
OUTDIR = os.path.join(ROOT, "docs", "survivorship")

MAX_GAP = 45  # days a price bar may sit from the membership date before it is "unknown"

# slug -> (indicesHistory name, per-index daily-close JSON under docs/ or None, index_monthly key or None)
INDEXES = {
    "nifty500": ("Nifty 500", "nifty500.json", "NIFTY 500"),
    "nifty50": ("Nifty 50", "nifty.json", "NIFTY 50"),
    "niftybank": ("Nifty Bank", "nifty_bank.json", "NIFTY BANK"),
    "niftynext50": ("Nifty Next 50", None, "NIFTY NEXT 50"),
    "nifty100": ("Nifty 100", None, "NIFTY 100"),
    "nifty200": ("Nifty 200", None, "NIFTY 200"),
    "niftymidcap50": ("Nifty Midcap 50", None, None),
    "niftymidcap100": ("Nifty Midcap 100", None, "NIFTY MIDCAP 100"),
    "niftymidcap150": ("Nifty Midcap 150", None, "NIFTY MIDCAP 150"),
    "niftysmallcap50": ("Nifty Smallcap 50", None, None),
    "niftysmallcap100": ("Nifty Smallcap 100", None, "NIFTY SMALLCAP 100"),
    "niftysmallcap250": ("Nifty Smallcap 250", None, "NIFTY SMALLCAP 250"),
    "niftylargemidcap250": ("Nifty LargeMidcap 250", None, None),
    "niftymidsmallcap400": ("Nifty MidSmallcap 400", None, None),
    "niftyit": ("Nifty IT", None, "NIFTY IT"),
    "niftypharma": ("Nifty Pharma", None, "NIFTY PHARMA"),
    "niftyauto": ("Nifty Auto", None, "NIFTY AUTO"),
    "niftyfmcg": ("Nifty FMCG", None, "NIFTY FMCG"),
    "niftymetal": ("Nifty Metal", None, "NIFTY METAL"),
    "niftyenergy": ("Nifty Energy", None, "NIFTY ENERGY"),
    "niftyrealty": ("Nifty Realty", None, "NIFTY REALTY"),
    "niftymedia": ("Nifty Media", None, "NIFTY MEDIA"),
    "niftyhealthcare": ("Nifty Healthcare", None, "NIFTY HEALTHCARE"),
    "niftyconsumerdurables": ("Nifty Consumer Durables", None, "NIFTY CONSR DURBL"),
    "niftyoilgas": ("Nifty Oil & Gas", None, "NIFTY OIL AND GAS"),
    "niftypsubank": ("Nifty PSU Bank", None, "NIFTY PSU BANK"),
    "niftymnc": ("Nifty MNC", None, "NIFTY MNC"),
    "niftysmeemerge": ("Nifty SME Emerge", "nifty_sme_emerge.json", None),
}
DEFAULT = [
    "nifty500",
    "nifty50",
    "niftybank",
    "niftysmeemerge",
]  # the member-bearing indices index-chart.html serves
# Indices whose point-in-time membership is NOT in indicesHistory (built from their own source, never merged into
# scripts/indices_history.json whose ~30 builders expect the main-board universe): slug -> (docs/ path, member note)
OWN_HISTORY = {
    "niftysmeemerge": (
        "nse_sme_emerge/history.json",
        "Membership: NSE Indices\u2019 own press releases \u2014 every quarterly review and every one-off exclusion "
        "since 2019 \u2014 walked back from NSE\u2019s official constituent list, with ticker renames folded to "
        "today\u2019s symbol; checked against NSE\u2019s archived official list of 3 Aug 2023 (147 of 147). "
        "Record starts 1 Jan 2020.",
    ),
}

COLS = [
    "sym",
    "name",
    "sector",
    "industry",
    "isin",
    "mcap",
    "status",
    "first",
    "fromStart",
    "last",
    "n",
    "days",
    "joinPx",
    "exitPx",
    "lastPx",
    "lastD",
    "retIn",
    "cagrIn",
    "retSince",
    "retAfter",
    "idxIn",
    "relIn",
    "maxDD",
    "upcoming",
    "st",
]


# ---------------------------------------------------------------- dates ----
def to_int(iso):
    return int(iso.replace("-", ""))


def to_iso(i):
    s = str(i)
    return s[:4] + "-" + s[4:6] + "-" + s[6:]


def to_date(i):
    s = str(i)
    return date(int(s[:4]), int(s[4:6]), int(s[6:]))


def days_between(a, b):
    """calendar days from int date a to int date b"""
    return (to_date(b) - to_date(a)).days


# ------------------------------------------------------------- rename fold ----
def resolve_chain(old, rmap):
    seen, target = {old}, rmap[old]
    while target in rmap and rmap[target] not in seen:
        seen.add(target)
        target = rmap[target]
    return target


def roster_key(sym, data, rmap):
    """roster name -> (bin key | None, how); DVR lines kept, DUMMY* skipped."""
    s = str(sym)
    if s.upper().startswith("DUMMY"):
        return None, "skip"
    if s in data:
        return s, "direct"
    if s in rmap:
        t = resolve_chain(s, rmap)
        if t in data:
            return t, "fold"
    return None, "unresolved"


# --------------------------------------------------------------- prices ----
def clean_series(e):
    """(dates[], closes[]) with non-positive closes removed."""
    ds, cs = [], []
    for d, c in zip(e["d"], e["c"], strict=False):
        if c and c > 0:
            ds.append(d)
            cs.append(c)
    return ds, cs


def bar_on_or_after(ds, cs, d):
    i = bisect_left(ds, d)
    if i < len(ds) and days_between(d, ds[i]) <= MAX_GAP:
        return i
    return None


def bar_before(ds, cs, d):
    """last bar strictly before d (the last session as a member when d is the exit effective date)"""
    i = bisect_left(ds, d) - 1
    if i >= 0 and days_between(ds[i], d) <= MAX_GAP:
        return i
    return None


def max_drawdown(cs, i0, i1):
    """worst % fall from a running peak over closes[i0..i1] inclusive; None when < 2 bars"""
    if i0 is None or i1 is None or i1 <= i0:
        return None
    peak, worst = cs[i0], 0.0
    for k in range(i0, i1 + 1):
        c = cs[k]
        if c > peak:
            peak = c
        dd = c / peak - 1
        if dd < worst:
            worst = dd
    return worst * 100


def pct(a, b):
    return None if (a is None or b is None or not a) else (b / a - 1) * 100


def r2(v):
    return None if v is None else round(v, 2)


# ------------------------------------------------------------ index level ----
def load_index_levels(daily_file, monthly_key):
    """sorted (int date, level) -- daily closes where the per-index JSON has them, month-end closes
    from index_monthly.json before that. Returns (dates[], levels[], provenance)."""
    daily = {}
    if daily_file:
        p = os.path.join(ROOT, "docs", daily_file)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for k, v in (json.load(f).get("px") or {}).items():
                    if v:
                        daily[to_int(k)] = v
    monthly = {}
    if monthly_key and os.path.exists(MONTHLY):
        with open(MONTHLY, encoding="utf-8") as f:
            recs = [r for r in json.load(f).get("indices", []) if r.get("key") == monthly_key]
        if recs:
            for y, arr in (recs[0].get("closes") or {}).items():
                for m, c in enumerate(arr or []):
                    if c:
                        nxt = date(int(y) + (1 if m == 11 else 0), 1 if m == 11 else m + 2, 1)
                        monthly[int((nxt - timedelta(days=1)).strftime("%Y%m%d"))] = c
    first_daily = min(daily) if daily else None
    merged = {d: c for d, c in monthly.items() if first_daily is None or d < first_daily}
    merged.update(daily)
    ds = sorted(merged)
    prov = []
    if daily:
        prov.append(f"{daily_file} daily closes {to_iso(min(daily))}..{to_iso(max(daily))}")
    if monthly:
        prov.append(
            f"index_monthly.json[{monthly_key}] month-end closes {to_iso(min(monthly))}..{to_iso(max(monthly))}"
        )
    return ds, [merged[d] for d in ds], "; ".join(prov) or "none"


def level_at(ids, ils, d):
    """index level on the last date <= d, within MAX_GAP days (month-end gaps fit); else None"""
    i = bisect_right(ids, d) - 1
    if i >= 0 and days_between(ids[i], d) <= MAX_GAP:
        return ils[i]
    return None


# --------------------------------------------------------------- stints ----
def stints_from_snapshots(snaps):
    """snaps: sorted [(eff int, set(names))] -> {name: [ {join, leave|None, fromStart}, ...]}"""
    out, open_st, prev = {}, {}, set()
    for i, (eff, S) in enumerate(snaps):
        for s in prev - S:
            open_st.pop(s)["leave"] = eff
        for s in S - prev:
            st = {"join": eff, "leave": None, "fromStart": i == 0}
            open_st[s] = st
            out.setdefault(s, []).append(st)
        prev = S
    return out


def build_index(slug, D, slim, rmap, sect, log=print):
    name, daily_file, monthly_key = INDEXES[slug]
    own = OWN_HISTORY.get(slug)
    if own:
        with open(os.path.join(ROOT, "docs", own[0]), encoding="utf-8") as f:
            raw = json.load(f).get(name, [])
    else:
        raw = slim.get("indicesHistory", {}).get(name, [])
    if not raw:
        raise SystemExit(f"no membership snapshots for {name!r} in {SLIM}")
    data, meta = D["data"], D.get("meta", {})
    data_end = to_int(D["end"])
    snaps = sorted(
        (
            to_int(s["effectiveDate"]),
            {x for x in s["symbols"] if not str(x).upper().startswith("DUMMY")},
        )
        for s in raw
    )
    in_force = [s for s in snaps if s[0] <= data_end]
    if not in_force:
        raise SystemExit("every {} snapshot is dated after the bin end {}".format(name, D["end"]))
    roster_asof, today_set = in_force[-1]
    # a later-dated snapshot is an ANNOUNCED reshuffle -- but only one that actually changes the
    # roster is worth reporting (NSE re-anchors an unchanged list at every half-year too)
    future = [s for s in snaps if s[0] > data_end]
    upcoming_eff = next((d for d, S in future if today_set != S), None)

    ids, ils, idx_prov = load_index_levels(daily_file, monthly_key)
    smeta = slim.get("meta", {})
    # own-history indices: NSE's official list names each CURRENT member's industry (the SME rows' dash meta only says
    # "NSE-SME" / "Unknown") — used as the sector column; past members keep what the metadata has
    own_ind = {}
    if own:
        mp = os.path.join(ROOT, "docs", os.path.dirname(own[0]), "members.json")
        if os.path.exists(mp):
            with open(mp, encoding="utf-8") as f:
                own_ind = {m["sym"]: m.get("industry") for m in json.load(f).get("members", [])}
    per_name = stints_from_snapshots(snaps)

    # group roster names by resolved bin key (two old names -> one series = one row)
    groups, how_tot = {}, {}
    for nm, sts in per_name.items():
        key, how = roster_key(nm, data, rmap)
        how_tot[how] = how_tot.get(how, 0) + 1
        gk = key if key else nm
        g = groups.setdefault(gk, {"key": key, "names": [], "stints": []})
        g["names"].append(nm)
        g["stints"].extend(sts)

    rows = []
    n_in = n_out = n_dead = n_untraced = 0
    for gk, g in groups.items():
        key = g["key"]
        sts = sorted(g["stints"], key=lambda s: s["join"])
        # merge stints that touch/overlap after a fold (old name leaves the day the new one joins)
        merged = []
        for s in sts:
            if merged and merged[-1]["leave"] is not None and s["join"] <= merged[-1]["leave"]:
                if s["leave"] is None or (
                    merged[-1]["leave"] is not None and s["leave"] > merged[-1]["leave"]
                ):
                    merged[-1]["leave"] = s["leave"]
                continue
            merged.append(dict(s))
        sts = merged
        # announced-only changes are reported, not applied
        upcoming = None
        if upcoming_eff:
            if any(s["join"] == upcoming_eff for s in sts):
                upcoming = "join " + to_iso(upcoming_eff)
            elif any(s["leave"] == upcoming_eff for s in sts):
                upcoming = "leave " + to_iso(upcoming_eff)
        applied = [s for s in sts if s["join"] <= data_end]
        for s in applied:
            if s["leave"] is not None and s["leave"] > data_end:
                s["leave"] = None  # announced exit: still a member today
        if not applied:
            continue  # joins only in an announced reshuffle: not a member yet

        e = data.get(key) if key else None
        m = meta.get(key, {}) if key else {}
        sm = smeta.get((key or "") + ".NS", {})
        sc = sect.get((key or "") + ".NS", {})
        in_today = any(nm in today_set for nm in g["names"])
        if in_today:
            status = "in"
            n_in += 1
        elif e is None:
            status = "untraced"
            n_untraced += 1
        elif m.get("alive"):
            status = "out"
            n_out += 1
        else:
            status = "dead"
            n_dead += 1

        ds, cs = clean_series(e) if e else ([], [])
        last_px = cs[-1] if cs else None
        last_d = ds[-1] if ds else None
        days = 0
        growth = 1.0
        idx_growth = 1.0
        idx_ok = True
        worst_dd = None
        st_out = []
        first_join_px = None
        last_exit_px = None
        for s in applied:
            j, l = s["join"], s["leave"]
            end = l if l is not None else data_end
            days += max(0, days_between(j, end))
            ji = bar_on_or_after(ds, cs, j) if ds else None
            xi = (
                (bar_before(ds, cs, l) if l is not None else (len(cs) - 1 if cs else None))
                if ds
                else None
            )
            jp = cs[ji] if ji is not None else None
            xp = cs[xi] if xi is not None else None
            if jp is not None and first_join_px is None:
                first_join_px = jp
            if l is not None and xp is not None:
                last_exit_px = xp
            r = pct(jp, xp)
            if r is not None:
                growth *= 1 + r / 100
            elif l is not None or jp is None:
                growth = (
                    None if growth is None else growth
                )  # keep; a window with no price simply does not compound
            dd = max_drawdown(cs, ji, xi)
            if dd is not None and (worst_dd is None or dd < worst_dd):
                worst_dd = dd
            a, b = level_at(ids, ils, j), level_at(ids, ils, end)
            if a and b:
                idx_growth *= b / a
            else:
                idx_ok = False
            st_out.append([to_iso(j), to_iso(l) if l is not None else None, r2(jp), r2(xp), r2(r)])
        ret_in = (growth - 1) * 100 if first_join_px is not None else None
        yrs = days / 365.25
        cagr = (
            ((growth ** (1 / yrs)) - 1) * 100
            if (ret_in is not None and yrs >= 1 and growth > 0)
            else None
        )
        idx_in = (idx_growth - 1) * 100 if idx_ok else None
        rel = (
            ((1 + ret_in / 100) / (1 + idx_in / 100) - 1) * 100
            if (ret_in is not None and idx_in is not None)
            else None
        )
        rows.append(
            [
                gk,
                m.get("name") or sm.get("name") or gk,
                own_ind.get(gk)
                or (None if sm.get("sector") == "NSE-SME" else sm.get("sector"))
                or sc.get("macro")
                or None,
                next(
                    (
                        v
                        for v in (sc.get("industry"), sm.get("industry"), m.get("ind"))
                        if v and not (own and v == "Unknown")
                    ),
                    None,
                ),
                m.get("isin"),
                r2(sm.get("mcap")) if sm.get("mcap") else None,
                status,
                to_iso(applied[0]["join"]),
                bool(applied[0].get("fromStart")),
                to_iso(applied[-1]["leave"]) if applied[-1]["leave"] is not None else None,
                len(applied),
                days,
                r2(first_join_px),
                r2(last_exit_px) if status != "in" else None,
                r2(last_px),
                to_iso(last_d) if last_d else None,
                r2(ret_in),
                r2(cagr),
                r2(pct(first_join_px, last_px)),
                r2(pct(last_exit_px, last_px)) if status != "in" else None,
                r2(idx_in),
                r2(rel),
                r2(worst_dd),
                upcoming,
                st_out,
            ]
        )
    rows.sort(key=lambda r: (r[6] != "in", r[0]))
    out = {
        "index": name,
        "slug": slug,
        "updated": D["end"],
        "dataEnd": D["end"],
        "snaps": len(snaps),
        "firstSnap": to_iso(snaps[0][0]),
        "lastSnap": to_iso(snaps[-1][0]),
        "rosterAsOf": to_iso(roster_asof),
        "upcoming": to_iso(upcoming_eff) if upcoming_eff else None,
        "nIn": n_in,
        "nOut": n_out,
        "nDead": n_dead,
        "nUntraced": n_untraced,
        "idxSeries": idx_prov,
        "source": "membership: %s[%s] (%d snapshots %s..%s); prices: sf bin adjusted closes to %s; "
        "roster names resolved %s"
        % (
            ("docs/" + own[0]) if own else "dash_slim.bin indicesHistory",
            name,
            len(snaps),
            to_iso(snaps[0][0]),
            to_iso(snaps[-1][0]),
            D["end"],
            json.dumps(how_tot, sort_keys=True),
        ),
        "cols": COLS,
        "rows": rows,
    }
    if own:
        out["memberNote"] = own[1]
    log(
        "%s: %d rows (in %d, out %d, dead %d, untraced %d) from %d snapshots; roster in force %s; upcoming %s; names %s"
        % (
            name,
            len(rows),
            n_in,
            n_out,
            n_dead,
            n_untraced,
            len(snaps),
            to_iso(roster_asof),
            to_iso(upcoming_eff) if upcoming_eff else "-",
            how_tot,
        )
    )
    return out


def main(argv):
    want = argv[1:] or DEFAULT
    if want == ["all"]:
        want = list(INDEXES)
    bad = [w for w in want if w not in INDEXES]
    if bad:
        raise SystemExit("unknown index slug(s) {} -- known: {}".format(bad, ", ".join(INDEXES)))
    D = json.loads(gzip.decompress(open(BIN, "rb").read()))
    slim = json.loads(gzip.decompress(open(SLIM, "rb").read()))
    rmap = json.load(open(RMAP, encoding="utf-8"))
    sect = json.load(open(SECT, encoding="utf-8")) if os.path.exists(SECT) else {}
    print(
        "bin: %d symbols, end %s; dash_slim: %d indices"
        % (len(D["data"]), D["end"], len(slim.get("indicesHistory", {}))),
        flush=True,
    )
    os.makedirs(OUTDIR, exist_ok=True)
    for slug in want:
        out = build_index(slug, D, slim, rmap, sect)
        p = os.path.join(OUTDIR, slug + ".json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
        print(f"wrote {p} ({os.path.getsize(p) / 1024.0:.0f} KB)", flush=True)


if __name__ == "__main__":
    main(sys.argv)
