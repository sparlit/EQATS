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
Daily INCREMENTAL updater for docs/sf_stock_data.bin (the survivorship-free
backtest dataset: close/turnover/high/low/open/volume/delivery%/VWAP).

Run daily (GitHub Actions): appends only the trading days missing since the
file's `end` — no 30-year refetch, no git bloat (the workflow publishes the
bin as a GitHub Release asset instead of committing it).

Base file: tries the release asset first, falls back to docs/sf_stock_data.bin.
Touches docs/.sf_updated when (and only when) new data was appended.

Run: python -X utf8 update_sf_data.py
"""
import datetime
import gzip
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "sf_stock_data.bin")
MARK = os.path.join(ROOT, "docs", ".sf_updated")
RELEASE_URL = "https://github.com/dhruvan246/stocks-dashboard/releases/download/data/sf_stock_data.bin"

sys.path.insert(0, HERE)
# build_sf_data's module-level code parses sys.argv[1:] as its own START/DAILY_FROM dates — hide our
# own args (e.g. --base) from it while importing, or it crashes trying to parse '--base' as a date.
_argv = sys.argv
sys.argv = _argv[:1]
import build_sf_data as B  # reuse fetch_day / parse_rows / jar (module-level code is harmless)

sys.argv = _argv

CA_FRACS = [
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


def ca_factor(r):
    if 0.75 <= r <= 1.30:
        return 1.0
    for f in CA_FRACS:
        if abs(r / f - 1) <= 0.08:
            return f
    return 1.0


# Known FALSE corporate-action detections: a market crash whose overnight drop ca_factor mis-read as
# a split, divided it out, and (after re-anchoring) mis-scaled the pre-crash history. NSE's CA feed
# never lists these (they aren't real actions), so build_corp_actions can't surface them and the
# 28-day self_heal window can't reach them. self_heal reconciles these UNCONDITIONALLY every run
# (keep the drop as a genuine move). Idempotent: once the baked-in mis-scale is undone, the bin's
# ex-date ratio already equals the raw ratio, so applied_f == 1 and it no-ops.
#   ADANIENT 2023-02-01/02 — Hindenburg crash + FPO withdrawal (2/3 x 3/4 = 1/2 false halving of all
#   pre-crash history -> a too-low 52w high -> wrongly passes Distance-from-52w-High filters in 2023)
LEGACY_FALSE_CA = [
    ("ADANIENT", 20230201),
    ("ADANIENT", 20230202),
    ("ADANIPOWER", 20200312),
    # COVID-19 crash, Mar-2020 (market-wide, no corporate action — verified vs NSE corp-actions):
    ("IDEA", 20200318),
    ("ASHOKLEY", 20200319),
    ("AXISBANK", 20200323),
    ("BAJAJFINSV", 20200323),
    ("BANDHANBNK", 20200323),
    ("CHOLAFIN", 20200323),
    ("EQUITAS", 20200323),
    ("M&MFIN", 20200323),
    ("MFSL", 20200323),
    # news-driven crashes (no corporate action):
    ("ZEEL", 20240123),  # Sony merger called off
    ("RECLTD", 20240604),  # 4-Jun-2024 election-result crash
    ("INDUSINDBK", 20250311),  # derivatives-accounting disclosure
    ("PAYTM", 20211118),
    ("PAYTM", 20211119),  # IPO listing crash
    ("IEX", 20250724),  # CERC market-coupling order
    # 2026-08-03 full-series audit vs Yahoo-raw + official bhavcopies (memory:
    # project-stocks-demerger-price-gap): five more crashes the >25%-drop inference had baked in
    # as splits — each verified: NSE CA feed EMPTY +-10d, raw bhavcopy fall matches the factor.
    ("SAMMAANCAP", 20190930),  # IBULHSGFIN -34.4% (Indiabulls crisis) read as 2/3
    ("SAMMAANCAP", 20200319),  # IBULHSGFIN -33.7% (COVID) read as 2/3
    ("YESBANK", 20190430),  # -29.2% Q4-loss shock read as 2/3
    ("ZEEL", 20190125),  # -26.6% Essel-crisis Friday read as 3/4
    ("DISHTV", 20190125),  # -33.2% same Friday read as 2/3
    ("RELINFRA", 20190206),
    ("RELINFRA", 20190207),  # -32.1% then -28.3% read as 2/3 x 2/3
    # IPO listing-day pops mis-read as reverse-splits (keep the real move):
    ("ROUTE", 20200921),
    ("INDIGOPNTS", 20210202),
    ("MTARTECH", 20210315),
    ("GRINFRA", 20210719),
    ("NYKAA", 20211110),
    ("IREDA", 20231129),
    ("PREMIERENE", 20240903),
]
# Auto-discovered crashes appended by scripts/audit_phantom_ca.py (weekly): a big fall with NO corporate
# announcement is a crash, not a split/bonus — keep the drop. Merged additively; missing/empty file is safe.
try:
    _pc = json.load(open(os.path.join(HERE, "phantom_crashes.json")))
    for _s, _ds in _pc.items():
        for _d in _ds:
            if (_s, int(_d)) not in LEGACY_FALSE_CA:
                LEGACY_FALSE_CA.append((_s, int(_d)))
except Exception:
    pass


def load_base():
    # The release asset is the MERGED source-of-truth (renamed tickers consolidated). We do NOT fall
    # back to the in-repo docs copy — that copy is an old UN-merged build, and appending to it would
    # publish bad data (renamed tickers split into stubs). On 3 transient failures, fail loud so the
    # workflow stops rather than silently regressing.
    last = None
    for attempt in range(3):
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(RELEASE_URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=180
            ).read()
            print("Base: release asset (%.1f MB)" % (len(raw) / 1048576))
            return json.loads(gzip.decompress(raw))
        except Exception as e:
            last = e
            print("Base: release fetch attempt %d failed (%s)" % (attempt + 1, e))
            time.sleep(10)
    msg = f"ABORT: could not fetch the merged release-asset base after 3 tries ({last}) — refusing to build from the un-merged in-repo copy"
    raise SystemExit(msg)


def _open_confirms(e, j, applied_f, off):
    """§87c open gate: does the ex-day OPEN print at the basis the OFFICIAL factor `off` implies?

    The bin stores the ADJUSTED open, so op[j]/c[j-1] is the raw open gap divided by whatever factor
    is currently baked across that boundary (`applied_f`) — multiply it back out to recover the raw
    (open/prev), then divide by the official factor. On a true corporate action that lands at ~1.0;
    an equity crash sits >= 1.19 because it opens near flat and falls intraday.

    Band [0.88, 1.12] calibrated on this repo's own live data (2026-08-12): 1,350 official actions
    verified applied in the served series give p5=0.9625, p50=1.0181, p95=1.0959, 97.0% <= 1.12 —
    agreeing with §87c's independent calibration on 566 ground-truth events (p5..p95 0.957..1.100)."""
    op = e.get("op")
    c = e.get("c")
    if not op or not c or j >= len(op) or not op[j] or not c[j - 1] or not applied_f or not off:
        return False
    return 0.88 <= (op[j] / c[j - 1]) * applied_f / off <= 1.12


def self_heal(data, CA_OFF, NOADJ, end_ymd, jar, window_days=28):
    """Belt-and-suspenders. Re-correct any split/bonus/demerger whose ex-date fell in the last
    ~4 weeks but was processed by an EARLIER daily run before NSE had published the action (so the
    incremental updater used inference and baked in the wrong treatment). For each recent official
    action we recover the factor the bin currently reflects (applied_f = raw_ratio / adjusted_ratio
    across the ex-date) and compare it to the official one; if they disagree we rescale the pre-ex
    history by correct_f/applied_f. Idempotent: once correct, applied_f == correct_f so it no-ops."""

    def od(y):
        return datetime.date(y // 10000, y // 100 % 100, y % 100).toordinal()

    # Normally only the last ~4 weeks (fresh actions the daily run might have mis-inferred before NSE
    # published them). SF_HEAL_WINDOW=<days> forces a one-time FULL-history reconciliation — needed when
    # corp_actions.json gains factors that were historically missing/mis-inferred (e.g. the "To Re.1"
    # face-value-split parser fix), so the whole back-history gets re-reconciled against the official set.
    window_days = int(os.environ.get("SF_HEAL_WINDOW", window_days))
    cutoff = od(end_ymd) - window_days
    events = []  # (sym, exYmd, official_split_bonus_factor_or_None, is_demerger)
    for sym, fl in CA_OFF.items():
        for ex, fac in fl.items():
            if od(ex) >= cutoff:
                events.append((sym, ex, fac, False))
    # CONTRADICTION GUARD (2026-08-11). A date can end up in BOTH maps when the feed files two
    # rows for it — AHLEAST 2022-10-06 carries an official 2/3 factor AND a scheme row, so
    # corp_actions.json holds factors[20221006]=0.666667 and noadjust[20221006]. The two events
    # then fight over the same bar every run ("divide the drop out" vs "keep it"), each pass
    # rescaling the pre-ex block x1.5 — AHLEAST's pre-2022 history was inflated x2.25 by two
    # full-window runs. An explicit split/bonus RATIO outranks a keep-drop flag: drop the
    # keep-drop side whenever the same date also carries a factor.
    _fact_dates = {(s, e) for s, fl in CA_OFF.items() for e in fl}
    for sym, exset in NOADJ.items():
        for ex in exset:
            if (sym, ex) in _fact_dates:
                continue
            if od(ex) >= cutoff:
                events.append((sym, ex, None, True))
    # Legacy false-CA corrections: reconciled every run regardless of age (idempotent), to converge
    # the release-asset loop on data the 28-day window + NSE-derived noadjust can never reach.
    for sym, ex in LEGACY_FALSE_CA:
        if not any(e[0] == sym and e[1] == ex for e in events):
            events.append((sym, ex, None, True))

    # Ledger DEMERGERS (scripts/demerger_adj.json): reconciled every run regardless of age
    # (idempotent, network-free — the raw ex-day ratio rides in the ledger). Converges bins where
    # the drop is still baked in, AND bins where an old build mis-inferred the drop as a split.
    # A ledger factor belongs to exactly ONE bar boundary — match by the RESOLVED drop-day index,
    # never by calendar proximity: VEDL's phantom-crash flag (20260501 -> bar 20260504) sits a day
    # after its demerger ex (20260430 -> bar 20260430); a +-days match let that event hijack the
    # factor onto the wrong boundary and block-mis-scale 6k bars. With bar-exact matching the
    # phantom event falls through to the generic raw-price reconciliation, which is what repairs
    # any such historical mis-scale.
    def _jat(sym_, ymd_):
        e_ = data.get(sym_)
        ds_ = e_.get("d") if e_ else None
        if not ds_:
            return None
        return next((k for k in range(len(ds_)) if ds_[k] >= ymd_), None)

    for dsym, dex in MANUAL_DEMERGERS:
        tj = _jat(dsym, dex)
        if tj is None:
            continue
        if not any(e[0] == dsym and _jat(dsym, e[1]) == tj for e in events):
            events.append((dsym, dex, None, True))
    dem_by_sym = {}
    for (dsym, dex), dv in MANUAL_DEMERGERS.items():
        dem_by_sym.setdefault(dsym, []).append((dex, dv))
    if not events:
        return 0
    try:
        _RAW = json.load(open(os.path.join(HERE, "crash_raw_prices.json")))
    except Exception:
        _RAW = {}
    daycache = {}
    # a renamed symbol's PRE-RENAME day rows carry the era ticker (TMPV's old rows say
    # TATAMOTORS), so raw_close on a current key misses them — try the rename-map aliases
    # (same rule build_demerger_adj uses). Matters for pre-2016 heal events (2026-08-11).
    try:
        _ren = json.load(open(os.path.join(HERE, "_rename_map.json")))
    except Exception:
        _ren = {}
    _alias = {}
    for _o, _n in _ren.items():
        _alias.setdefault(_n, []).append(_o)

    def raw_close(ymd, sym):
        if ymd not in daycache:
            rows = B.fetch_day(datetime.date(ymd // 10000, ymd // 100 % 100, ymd % 100), jar) or []
            daycache[ymd] = {r[0]: r[1] for r in rows}
        v = daycache[ymd].get(sym)
        if v is None:
            for _a in _alias.get(sym, ()):
                v = daycache[ymd].get(_a)
                if v is not None:
                    break
        if v is None:  # CI runners get blocked/rate-limited fetching NSE's archive -> fall back to the
            v = (_RAW.get(sym) or {}).get(str(ymd))  # committed raw ex-date prices so self_heal still works
        return v

    healed = 0
    _quant_skips = []
    PX_FLOOR_LOG = 0.25
    for sym, ex, off, is_dem in events:
        e = data.get(sym)
        if not e or not e.get("d"):
            continue
        ds = e["d"]
        j = next((k for k in range(len(ds)) if ds[k] >= ex), None)  # drop day = first day on/after ex
        if j is None or j < 1:
            continue
        c = e["c"]
        if not c[j] or not c[j - 1]:
            continue
        # QUANTIZATION GUARD (2026-08-11). Prices are stored to 2 decimals, so on a sub-rupee
        # series the boundary ratio is dominated by rounding — 0.02/0.01 is EXACTLY 2.0 — and the
        # recovered applied_f is noise. Healing on noise never converges: BIRLACOT, FARMAXIND,
        # VKSPL and VISUINTL (all long-standing phantom_crashes entries, so reconciled on EVERY
        # run) were being rescaled x0.5 nightly, eroding their history toward 0.00 — measured
        # 0.05 -> 0.01 with 1,661 closes already at zero. A heal is only trustworthy when both
        # boundary closes carry the precision to express it (0.005/0.25 = 2%).
        PX_FLOOR = PX_FLOOR_LOG
        if c[j] < PX_FLOOR or c[j - 1] < PX_FLOOR:
            if len(_quant_skips) < 40:
                _quant_skips.append((sym, ex, round(c[j - 1], 4), round(c[j], 4)))
            continue
        # demerger with a ledger factor on THIS EXACT bar boundary? its committed raw ex-day ratio
        # spares the bhavcopy refetch. Bar-exact only — a nearby event (phantom crash a day later)
        # must NOT borrow the factor; it falls through to the raw-price reconciliation below.
        dem = None
        if is_dem:
            for dex, dv in dem_by_sym.get(sym, []):
                jj = next((k for k in range(len(ds)) if ds[k] >= dex), None)
                if jj == j:
                    dem = dv
                    break
        if dem is not None:
            raw_ratio = dem[1]
        else:
            re_ex, re_prev = raw_close(ds[j], sym), raw_close(ds[j - 1], sym)
            if not re_ex or not re_prev:
                continue
            raw_ratio = re_ex / re_prev
        adj_ratio = c[j] / c[j - 1]
        if adj_ratio <= 0:
            continue
        applied_f = raw_ratio / adj_ratio  # factor the bin currently reflects across the ex-date
        if applied_f <= 0:
            continue
        # correct_f = EXACTLY what the rebuild would apply now, given the official action AND the
        # real drop (same reconciliation guard — so combined split+bonus, ex-date moves and misparses
        # resolve to inference just like the rebuild, instead of being force-overridden).
        if dem is not None:
            correct_f = dem[0]  # demerger: scale out the SPOS open-gap (value moved to the spin-off)
        elif off is not None and 0.75 <= raw_ratio / off <= 1.30:
            correct_f = off
        elif off is not None and _open_confirms(e, j, applied_f, off):
            # THE OPEN ARBITRATES (§87c) — mirror of the same second chance in build_sf_data's
            # reconcile. A real action landing on a violent day fails the close-to-close test above;
            # its ex-day OPEN still prints at the adjusted basis. Without this branch a full-window
            # run (SF_HEAL_WINDOW) would compute correct_f = ca_factor(raw_ratio) = 1.0 for exactly
            # these events and UNDO the ca_open_arbitrated ledger's heal — JINDALSTEL-2008 would be
            # re-inflated x5 by the very pass meant to converge it.
            correct_f = off
        elif is_dem and not (0.75 <= raw_ratio <= 1.30):
            correct_f = 1.0
        else:
            correct_f = ca_factor(raw_ratio)
        corr = correct_f / applied_f
        if abs(corr - 1) > 0.02:  # baked-in treatment disagrees with the rebuild's -> fix
            for key in ("c", "h", "l", "op", "vw"):
                if key in e:
                    e[key] = [round(x * corr, 2) for x in e[key][:j]] + e[key][j:]
            kind = (
                (f"demerger f={correct_f:.4f}")
                if dem is not None
                else ("demerger:keep-drop" if correct_f == 1.0 else f"split/bonus f={correct_f:.4f}")
            )
            print(
                "  SELF-HEAL %s ex %d: was f=%.4f -> %s  (rescaled %d pre-ex points x%.4f)"
                % (sym, ex, applied_f, kind, j, corr)
            )
            healed += 1
    if _quant_skips:
        print(
            "  self-heal skipped %d event(s) below the 2-decimal precision floor (sub-%.2f "
            "prices make the boundary ratio pure rounding): %s"
            % (
                len(_quant_skips),
                PX_FLOOR_LOG,
                ", ".join("%s@%d(%.2f/%.2f)" % (s, x, a, b) for s, x, a, b in _quant_skips[:8]),
            )
        )
    return healed


# HAND-VERIFIED one-off rights adjustments. POLICY is raw NSE tape (rights are NOT adjusted — see the
# project-stocks-price-verification memory / build note), because a blanket rights adjustment wrongly
# pulls low-priced pre-rights lows across the "2x above 52w-low" filter (PNBHOUSING/SUZLON). But
# Trendlyne/StockView DO carry a rights-adjusted series for a FEW specific stocks, so to match the
# reference exactly on those cells we scale their PRE-ex prices by the TERP factor here — per stock,
# never blanket. Each entry: (ticker, ex_ymd, terp_factor, raw_ex_drop_ratio).
#   SAMMAANCAP (ex-IBULHSGFIN): rights 1:2 @ Rs150 ex 2024-02-01. TERP=0.8914; raw ex-date close 193.90
#   / prev 222.50 = 0.8714. Verified vs Trendlyne (d52 9.63, d52low 131.15) — raw would show 19.44 /
#   106.05 and drop it from the Feb-2024 picks. No F&O / split / ISIN-change rule distinguishes it.
MANUAL_RIGHTS = [
    ("SAMMAANCAP", 20240201, 0.8914, 0.8714),
    # --- 2026-07-10: six rights events surfaced by the StockView reconciliation (their d52 = textbook
    # TERP, verified to the decimal) + M&MFIN's 2nd rights nobody flagged. All ex-dates NSE-official
    # (corporates-corporateActions API); factor = TERP/cum-close from raw prices; raw_drop = the ex-day
    # close ratio CURRENTLY in the series (idempotence anchor). Dates below = the actual ex-TRADING day
    # (first session whose price is ex-rights), which for M&MFIN-2020 is 23-Jul (NSE exDate 22-Jul).
    # M&MFIN 2020 rights 1:1 @ Rs50: the >25% ex-drop was mis-baked as a 2/3 split-inference at build
    # time; true TERP factor 0.6083, so this entry holds the residual CORRECTION 0.6083/(2/3)=0.9125
    # against the already-scaled series (current ex ratio 0.9659 -> 1.0585 once applied).
    ("M&MFIN", 20200723, 0.9125, 0.9659),
    ("CGCL", 20230217, 0.9459, 0.9350),  # Rights 11:64 @ 475, cum 752.44 -> TERP 711.75
    ("PNBHOUSING", 20230405, 0.8282, 0.8563),  # Rights 29:54 @ 275, cum 540.90 -> TERP 448.00
    ("SOBHA", 20240619, 0.9733, 0.9347),  # Rights 6:47 @ 1651, cum 2159.70 -> TERP 2102.11
    ("UPL", 20241126, 0.9592, 0.9705),  # Rights 1:8  @ 360,  cum 568.55 -> TERP 545.38
    ("M&MFIN", 20250514, 0.9731, 1.0131),  # Rights 1:8  @ 194,  cum 256.30 -> TERP 249.42 (2nd rights)
    ("ADANIENT", 20251117, 0.9695, 0.9782),  # Rights 3:25 @ 1800, cum 2516.80 -> TERP 2440.00
]
# --- 2026-07-10: POLICY WIDENED (user) — TERP-adjust EVERY parseable rights issue, so d52 is correct at ANY
# filter threshold (10, 25, ...), not just the cells hand-flagged above. scripts/rights_terp.json holds the
# generated entries (202: all NSE rights 2014→date with parseable terms × price data; same tuple format),
# built by the rights sweep from the official corporates-corporateActions feed + TERP vs raw cum-close.
# Skipped there (documented in the sweep): partly-paid (ABFRL/TATASTEEL — different economics), unparseable
# subjects, and deep-discount events whose ex-drop the old build already baked as a split-inference (all
# non-N500 microcaps except IDEA-2019/NCC-2014, hand-verified immaterial: d52 nowhere near any threshold).
# Regenerate after new rights: re-run the sweep (memory: project-stocks-stockview-comparison).
try:
    _rt = json.load(open(os.path.join(ROOT, "scripts", "rights_terp.json")))
    _seen = {(s, e) for s, e, _f, _r in MANUAL_RIGHTS}
    MANUAL_RIGHTS += [tuple(x) for x in _rt if (x[0], x[1]) not in _seen]
except Exception as _e:
    print(f"  (rights_terp.json not loaded: {_e})")

# --- DEMERGER price adjustment (2026-08-03). A demerger is not a loss — holders receive the
# spin-off's shares — but the raw tape keeps the ex-date value separation as a price fall, so every
# trailing-window factor (ret6m/mdd6/d52/rangePos/...) read a spin-off as a crash for the following
# 6-12 months (SKFINDIA 2025-10 ret6m -45% vs ~flat truth; NMDC 2023-03 -12.7% vs strongly positive).
# scripts/demerger_adj.json (built by build_demerger_adj.py from the official CA feed, demerger/
# spin-off subjects ONLY) holds [sym, exTradingYmd, factor, raw_drop]: factor = ex-date SPOS open /
# prev close — the exchange's own price discovery for the residual company — and raw_drop = the raw
# ex-day close ratio (reconciliation anchor, so CI never refetches old bhavcopies). self_heal scales
# pre-ex history by `factor` EVERY run (idempotent; also converges old bins that mis-inferred a
# demerger drop as a split). Crash keep-drops (phantom_crashes / LEGACY_FALSE_CA / MANUAL_NOADJUST)
# are never in this ledger and keep their drops. After a NEW demerger: run build_demerger_adj.py
# (the workflow does, right after build_corp_actions.py) — until then the day-of run keeps the drop.
try:
    MANUAL_DEMERGERS = {
        (x[0], int(x[1])): (float(x[2]), float(x[3]))
        for x in json.load(open(os.path.join(ROOT, "scripts", "demerger_adj.json")))
    }
except Exception as _e:
    MANUAL_DEMERGERS = {}
    print(f"  (demerger_adj.json not loaded: {_e})")


def apply_manual_rights(data):
    """Scale each MANUAL_RIGHTS stock's pre-ex prices by its TERP factor. Idempotent WITHOUT a marker:
    the ex-date ratio in the series is `raw_drop` before adjustment and `raw_drop/factor` after, so we
    re-apply only when the current ratio is still closer to the raw drop. Scale-invariant, so a later
    split/bonus re-anchoring the whole series won't fool it or double-apply."""
    n = 0
    for sym, ex, factor, raw_drop in MANUAL_RIGHTS:
        e = data.get(sym)
        if not e or not e.get("d"):
            continue
        ds, c = e["d"], e["c"]
        j = next((k for k in range(len(ds)) if ds[k] >= ex), None)  # first day on/after ex
        if j is None or j < 1 or not c[j - 1] or not c[j]:
            continue
        cur = c[j] / c[j - 1]  # ex-date ratio currently baked into the series
        if abs(cur - raw_drop) < abs(cur - raw_drop / factor):  # still ~raw drop -> not yet applied
            for key in ("c", "h", "l", "op", "vw"):
                if key in e:
                    e[key] = [round(x * factor, 2) for x in e[key][:j]] + e[key][j:]
            n += 1
            print("  MANUAL-RIGHTS %s ex %d x%.4f (%d pre-ex points -> Trendlyne parity)" % (sym, ex, factor, j))
    return n


# OFFICIAL split/bonus factors whose ex-day CLOSE ratio the [0.75,1.30] reconcile window rejects but
# whose ex-day OPEN prints at the adjusted basis — the record is right, the close is contaminated by a
# genuine violent move the same day (§87a failure mode 1; §87c "the OPEN arbitrates"). build_sf_data
# now accepts these itself, but the LIVE series is the release asset + daily appends and self_heal only
# reaches ex-dates inside its 28-day window, so an old mis-baked action can never converge on its own.
# This pass runs EVERY run, network-free (the ledger carries the raw ex-day ratio, so no bhavcopy
# refetch) and idempotent by the apply_manual_rights test. See scripts/ca_open_arbitrated.json.
try:
    CA_ARBITRATED = [
        tuple(x[:4]) for x in json.load(open(os.path.join(ROOT, "scripts", "ca_open_arbitrated.json")))["events"]
    ]
except Exception as _e:
    CA_ARBITRATED = []
    print(f"  (ca_open_arbitrated.json not loaded: {_e})")


def apply_ca_arbitrated(data):
    """Divide out each open-arbitrated official split/bonus the close-ratio guard let through.
    Same idempotence test as apply_manual_rights: the ex-date ratio is `raw_drop` before the
    adjustment and `raw_drop/factor` after, so a series that already carries the factor — because
    it was rebuilt from scratch, or healed on an earlier run — is a no-op. Scale-invariant."""
    n = 0
    for sym, ex, factor, raw_drop in CA_ARBITRATED:
        e = data.get(sym)
        if not e or not e.get("d"):
            continue
        ds, c = e["d"], e["c"]
        j = next((k for k in range(len(ds)) if ds[k] >= ex), None)  # first day on/after ex
        if j is None or j < 1 or not c[j - 1] or not c[j]:
            continue
        # PRECISION FLOOR (§87e-bis): at 2-decimal storage a sub-rupee series cannot express the
        # adjusted level, so the ratio test above is pure rounding and the pass re-fires for ever.
        # Measured on SOUISPAT (0.35 -> 0.04 across its 1/10): pass 2 wants another x1.1667 and its
        # 979 pre-ex bars collapse to 17 distinct values. Excluded by class, not healed. (§87g)
        if c[j] < 0.25 or c[j - 1] < 0.25:
            print(
                "  CA-OPEN-ARB %s ex %d SKIPPED: sub-Rs0.25 closes (%.2f/%.2f) — heal would not converge"
                % (sym, ex, c[j - 1], c[j])
            )
            continue
        cur = c[j] / c[j - 1]  # ex-date ratio currently baked into the series
        if abs(cur - raw_drop) < abs(cur - raw_drop / factor):  # still ~raw drop -> not yet applied
            for key in ("c", "h", "l", "op", "vw"):
                if key in e:
                    e[key] = [round(x * factor, 2) for x in e[key][:j]] + e[key][j:]
            n += 1
            print(
                "  CA-OPEN-ARB %s ex %d x%.6f (%d pre-ex points; ratio %.6f -> %.6f)"
                % (sym, ex, factor, j, cur, cur / factor)
            )
    return n


# ---------------------------------------------------------------------------
# WEEKEND SPECIAL SESSIONS — budget Saturdays, weekend Diwali-muhurat sessions and the 2024
# DR-drill Saturdays. Every daily enumerator in this repo skipped Sat/Sun until 2026-08-03, so
# these real trading days are missing from the series entirely — which made the 52w high/low
# provably wrong for 55-147 stocks for up to a year after each budget Saturday (VOLTAS's true
# 52w low, set 2025-02-01, was invisible for 206 trading days). The pass below INSERTS each
# date's bhavcopy bar in place, scaling prices onto the series' CA-adjustment level with
# f = adjusted_prev_close / RAW prev close taken from the PREVIOUS day's own bhavcopy (never
# this file's PREV_CLOSE column, which NSE mis-states on random days — see the chain-on-actual-
# ratios note in build_sf_data). Idempotent: a date already present (sentinel check) costs
# nothing. Rows come from the tracked ledger scripts/weekend_sessions.json.gz (CI runners can't
# always reach the old NSE archive), falling back to a live fetch for dates not in it.
# Only dates VERIFIED to have a real bhavcopy belong in this list. Found by sweeping EVERY
# Sat/Sun 2002->2026-08 for a bhavcopy and keeping files that differ from BOTH neighbouring
# sessions (>300 rows; NSE re-serves the prior session's file on non-trading days, so
# "identical to Friday" = no session). The 2026-08-03 sweep found exactly these 30.
_WEEKEND_CONFIRMED = [
    (2003, 3, 22),
    (2003, 10, 25),
    (2003, 11, 15),  # early special Sats (10-25 = muhurat)
    (2004, 4, 17),
    (2004, 10, 9),
    (2005, 6, 4),
    (2005, 11, 26),
    (2006, 4, 29),
    (2006, 6, 25),
    (2006, 10, 21),  # 10-21 = muhurat Sat
    (2009, 10, 17),  # muhurat Sat
    (2010, 2, 6),  # extended-hours test Sat
    (2012, 1, 7),
    (2012, 3, 3),
    (2012, 4, 28),
    (2012, 9, 8),  # exchange special live Sats
    (2013, 5, 11),
    (2013, 11, 3),  # 11-03 = muhurat Sun
    (2014, 3, 22),
    (2015, 2, 28),  # Budget Saturday (full session)
    (2016, 10, 30),  # muhurat Sun
    (2019, 10, 27),  # muhurat Sun
    (2020, 2, 1),  # Budget Saturday (full session)
    (2020, 11, 14),  # muhurat Sat
    (2023, 11, 12),  # muhurat Sun
    (2024, 1, 20),  # special session (Ram-Mandir-week Sat)
    (2024, 3, 2),
    (2024, 5, 18),  # DR-site-switch special live Sats
    (2025, 2, 1),  # Budget Saturday (full session)
    (2026, 2, 1),  # Budget SUNDAY (full session)
]
# WEEKDAY sessions the bin has NO bars for although NSE traded (Nifty has a close, a bhavcopy exists
# with >1,000 rows that differ from the prior day). Found 2026-08-23 by counting stock bars per Nifty
# session 2007→ (DATA_RUNBOOK §105): 13 holes, 12 verified (1,200-1,600 rows each, closes differ from
# the prior day). 2009-03-31 is a MONTH-END, so every month-end screen that day priced the whole
# universe off 30-Mar (SANOFI/GODREJCP wrongly failed d52<=10 vs quantmac). Same insert path as the
# weekend specials — the ledger carries each day's rows + prior-day anchors. NOT listed: 2021-11-04
# (muhurat Thursday) — NSE's archive serves the 03-Nov file for it (1,829/1,829 closes identical),
# so there is no session file to insert; the misdirect guard below would skip it anyway.
_WEEKDAY_MISSING_CONFIRMED = [
    (2008, 2, 19),
    (2009, 3, 31),
    (2010, 10, 14),
    (2010, 10, 26),
    (2014, 2, 21),
    (2014, 7, 25),
    (2014, 10, 14),
    (2015, 9, 3),
    (2016, 8, 17),
    (2016, 11, 17),
    (2017, 3, 24),
    (2017, 3, 27),
]
WEEKEND_SESSIONS = [datetime.date(*t) for t in _WEEKEND_CONFIRMED + _WEEKDAY_MISSING_CONFIRMED]


def insert_weekend_sessions(data, j, old2new=None):
    """Insert missing weekend special-session bars in place. Returns bars inserted.

    old2new: MANUAL_MERGE's old->new ticker map. A session traded under a since-merged old
    symbol (GET&D's 2019 muhurat, ADORWELD's pre-rename Saturdays…) must land on the SURVIVOR
    series — without the mapping those rows skip as "unknown symbol" and 200+ real session
    bars stay lost after a rename merge (measured 2026-08-11: 233 ledger rows under merged-away
    keys). The f = stored/raw anchor below already puts the bar on the target's adjusted scale."""
    import bisect

    ledger = {}
    lp = os.path.join(HERE, "weekend_sessions.json.gz")
    if os.path.exists(lp):
        try:
            ledger = json.load(gzip.open(lp, "rt", encoding="utf-8"))
        except Exception as ex:
            print(f"  weekend ledger unreadable ({ex}) — falling back to live fetch")

    def has(sym, ymd):
        e = data.get(sym)
        ds = e.get("d") if e else None
        if not ds:
            return False
        i = bisect.bisect_left(ds, ymd)
        return i < len(ds) and ds[i] == ymd

    # As-printed ERA symbol -> surviving bin key. old2new covers MANUAL_MERGE's pairs only; renames the
    # ISIN auto-merge consolidated long ago (AVENTIS->SANOFI, HEROHONDA->HEROMOTOCO, …) print their era
    # symbol in that day's bhavcopy and skipped as "unknown symbol" — measured on the 2009-03-31 insert:
    # 216 of 1,236 rows. Walk scripts/_rename_map.json until a key the bin holds. A symbol the bin holds
    # under its own name is never redirected (recycled tickers keep their own series, §89), and the
    # anchor/plausibility gates below still apply to every re-homed row.
    try:
        _rm = json.load(open(os.path.join(HERE, "_rename_map.json")))
    except Exception:
        _rm = {}

    def _survivor(sym):
        s = (old2new or {}).get(sym, sym)
        if s in data:
            return s
        seen = set()
        while s not in data and s in _rm and s not in seen:
            seen.add(s)
            s = _rm[s]
        return s

    total = 0
    for day in WEEKEND_SESSIONS:
        ymd = int(day.strftime("%Y%m%d"))
        if any(has(s, ymd) for s in ("RELIANCE", "SBIN", "ITC")):
            continue  # already inserted — zero-cost steady state
        led = ledger.get(str(ymd)) or {}
        rows = led.get("rows") or B.fetch_day(day, j)
        if not rows:
            print(f"  WEEKEND {day}: no bhavcopy available — skipped")
            continue
        if len(rows) < 300:  # stub/corrupt archive file (2010-05-16 has 7 rows), not a session
            print("  WEEKEND %s: only %d rows — stub file, skipped" % (day, len(rows)))
            continue
        prev_raw = led.get("prev") or {}
        prev_ymd = led.get("prevDate") or 0  # date the `prev` anchors belong to (ledger-stamped)
        _day_raw = {}  # per-date raw closes fetched for holed series
        if not prev_raw:  # walk back to the previous trading day's file
            d0 = day - datetime.timedelta(days=1)
            for _ in range(7):
                prows = B.fetch_day(d0, j)
                if prows:
                    prev_raw = {r[0]: r[1] for r in prows}
                    prev_ymd = int(d0.strftime("%Y%m%d"))
                    break
                d0 -= datetime.timedelta(days=1)
        # misdirect guard: NSE's per-day URL can serve the PRIOR day's file — a "session" whose
        # closes are ~all identical to the previous trading day is that file, not a session.
        if prev_raw:
            same = tot = 0
            for r in rows:
                pv = prev_raw.get(r[0])
                if pv:
                    tot += 1
                    same += abs(pv - r[1]) < 0.005
            if tot > 500 and same / tot > 0.99:
                print(f"  WEEKEND {day}: file duplicates the prior day — skipped")
                continue
        ins = skip = 0
        for r in rows:
            osym, c, _p, t = r[0], r[1], r[2], r[3]
            sym = _survivor(osym)  # merged-away / era ticker -> survivor series
            h = r[4] if len(r) > 4 else c
            l = r[5] if len(r) > 5 else c
            o_ = r[6] if len(r) > 6 else c
            v = r[7] if len(r) > 7 else 0
            dlv = r[8] if len(r) > 8 else 0
            vw = r[9] if len(r) > 9 else 0
            e = data.get(sym)
            if not e or not e.get("d") or any(k not in e for k in ("c", "t", "h", "l", "op", "v", "dv", "vw")):
                skip += 1
                continue  # unknown symbol — nothing to anchor to
            ds = e["d"]
            i = bisect.bisect_left(ds, ymd)
            if i < len(ds) and ds[i] == ymd:
                continue  # this symbol already has the bar
            if i == 0:
                skip += 1
                continue  # listed ON the session — no prior bar to anchor
            # The anchor must be the raw close of the SAME date as our last stored bar. The prior
            # session's file is that date only when the series has no hole just before the session;
            # BEPL's tape lacks 15-25 Oct 2010, so pairing its 14-Oct stored close with NSE's 25-Oct
            # close (or the file's PREV_CLOSE column) scaled the 26-Oct insert 3% low (measured
            # 2026-08-23 vs Yahoo: 27.22 for 28.03). So: prior-day file when the dates agree, else
            # that exact date's own bhavcopy (cached per date), else leave the row out — never guess.
            pdate = ds[i - 1]
            if pdate == prev_ymd:
                raw_prev = prev_raw.get(osym)
            else:
                if pdate not in _day_raw:
                    try:
                        _d = datetime.date(pdate // 10000, (pdate // 100) % 100, pdate % 100)
                        _day_raw[pdate] = {r[0]: r[1] for r in (B.fetch_day(_d, j) or [])}
                    except Exception:
                        _day_raw[pdate] = {}
                raw_prev = _day_raw[pdate].get(osym)
            if not raw_prev:
                skip += 1
                continue
            f = e["c"][i - 1] / raw_prev  # CA-adjustment level at the insertion point
            adj_c = round(c * f, 2)
            # implausible day move vs the neighbour = ex-date-on-session edge or bad anchor -> leave out
            if not (0.01 < f < 100) or not (0.6 <= adj_c / e["c"][i - 1] <= 1.6):
                skip += 1
                continue
            hi = round(max(h, c) * f, 2)
            lo_ = round((min(l, c) if l > 0 else c) * f, 2)
            opx = round(o_ * f, 2) if o_ > 0 else adj_c
            vwx = round(vw * f, 2) if vw > 0 else adj_c
            e["d"].insert(i, ymd)
            e["c"].insert(i, adj_c)
            e["t"].insert(i, round(t, 1))
            e["h"].insert(i, hi)
            e["l"].insert(i, lo_)
            e["op"].insert(i, opx)
            e["v"].insert(i, int(v))
            e["dv"].insert(i, round(dlv, 2) if dlv else 0)
            e["vw"].insert(i, vwx)
            ins += 1
        total += ins
        print("  WEEKEND %s: inserted %d bars (%d rows skipped)" % (day, ins, skip))
    return total


def normalize_turnover_units(data):
    """Force every stored turnover onto ONE unit: ₹ LACS. Returns bars converted.

    THE DEFECT (runbook §88a, measured 2026-08-11 on 9.31M classifiable bars): `t` is whatever
    the day's bhavcopy carried — the old NSE zip (TOTTRDVAL) is RAW RUPEES, sec_bhavdata_full
    (TURNOVER_LACS) is LACS. Result: 1996-2019 is rupees, 2020+ is lacs, plus strays both ways
    (9,845 lacs bars inside 2019, 1,974 rupee bars in 2022 — NSE served the old file on
    2022-08-08). Everything downstream states LACS (TURN_OPTS, the "Avg daily turnover (₹ lacs)"
    factor, build_stock_slices' `t`), so a turnover FLOOR compared a rupee number against a lacs
    threshold and passed ~every stock before 2020: pre-2020 backtest universes were silently
    unfloored, and any window spanning the seam saw a 1e5 cliff in the turnover factor.

    THE TEST — r = t / (c * v). `c` is split-ADJUSTED while `t` and `v` are RAW, so r is just the
    cumulative adjustment factor (rupee bar) or that factor / 1e5 (lacs bar). **Price cancels**,
    which is why this beats the t/v ("≈ average traded price") test build_nifty500_turnover.py
    uses: that one misreads sub-₹1 penny stocks as lacs and inflates them 1e5x, and it must lean
    on a per-date median to stay safe. Measured, r is sharply bimodal with an EMPTY band between
    10^-3.0 and 10^-1.3, so the two DECISIVE_* cuts below sit in genuine empty space.

    Bars that cannot self-classify (measured: 43,779 with a ZERO close, plus any with no volume)
    fall back to the day's verdict, because the unit is a WHOLE-DAY property — one file per day,
    so every stock on a date shares its unit (measured: 7,556 of 7,576 dates unanimous). The 20
    mixed dates are late-2019 days where a LATER backfill (BZ series, weekend sessions) spliced
    modern-format bars into an old-format day, so the per-BAR verdict deliberately wins wherever
    it exists — a pure per-date rule would re-break those 449 bars.

    The verdict is per DAY, off that day's MEDIAN r — never a per-bar absolute cut. A per-bar cut
    is NOT idempotent: 601 floor-priced bars (adjusted close ₹0.01 — DHANUS, CIMCOBIRLA…) carry an
    adjustment factor near 1e4, so one division leaves them still above any fixed rupee threshold
    and a second pass divides them AGAIN. The median is immune to those outliers, and it is what
    makes the whole function provably idempotent: converting a day divides its median by 1e5 too,
    so the day reads lacs forever after (§87e-bis — run it twice, the second pass MUST report 0).

    Within a rupee day, a bar sitting >=STRAY_RATIO below that day's median is a modern-format
    splice (BZ backfill / weekend sessions wrote lacs bars into old-format days — 9,845 of them in
    2019) and is left alone. That test is RELATIVE, so it too cannot re-fire once a day converts.
    """
    LACS_MED_CUT = 0.01  # a DAY's median r: ~1-3 on a rupee day, ~1e-5 on a lacs day (empty band between)
    STRAY_RATIO = 1e4  # a bar this far BELOW its day's median is already-lacs (unit gap is 1e5)

    samples = {}  # ymd -> [r, ...]
    for e in data.values():
        ds, ts = e.get("d") or [], e.get("t") or []
        cs = e.get("c") or []
        vs = e.get("v") or []
        for i in range(min(len(ds), len(ts), len(cs), len(vs))):
            t, c, v = ts[i], cs[i], vs[i]
            if t > 0 and c > 0 and v > 0:
                samples.setdefault(ds[i], []).append(t / (c * v))
    import statistics as _st

    med = {d: _st.median(rs) for d, rs in samples.items()}
    # A date with no measurable bar (only zero-close rows) inherits the nearest date that has one —
    # the unit is a property of the FILE served that day, and adjacent days come from the same era.
    known = sorted(med)

    def day_med(ymd):
        if ymd in med:
            return med[ymd]
        if not known:
            return None
        import bisect as _bi

        j = _bi.bisect_left(known, ymd)
        cands = [k for k in (j - 1, j) if 0 <= k < len(known)]
        return med[min(cands, key=lambda k: abs(known[k] - ymd))] if cands else None

    converted = 0
    for e in data.values():
        ds, ts = e.get("d") or [], e.get("t") or []
        cs = e.get("c") or []
        vs = e.get("v") or []
        n = len(ds)
        for i in range(min(n, len(ts))):
            t = ts[i]
            if t <= 0:
                continue
            m = day_med(ds[i])
            if m is None or m <= LACS_MED_CUT:
                continue  # a lacs day — nothing to do
            c = cs[i] if i < len(cs) else 0
            v = vs[i] if i < len(vs) else 0
            if c > 0 and v > 0 and (t / (c * v)) * STRAY_RATIO < m:
                continue  # modern-format bar spliced into an old-format day
            nt = t / 1e5
            # keep small values honest (a penny stock's whole day can be < 1 lac); large ones stay
            # at the file's usual 1dp so the ~190 MB payload doesn't grow for no information.
            ts[i] = round(nt, 4) if nt < 100 else round(nt, 1)
            converted += 1
    return converted


def insert_bz_history(data):
    """Splice in the series-BZ bars that build_sf_data's old ("EQ","BE") filter threw away.

    BZ is trade-for-trade + surveillance: a company that has not complied with a listing/regulatory
    requirement. It is still LISTED and still trades every session, but until 2026-08-10 we never
    ingested it, so a stock's series simply STOPPED the day it was penalised into BZ (38 of NSE's 39
    current BZ symbols were stale in the bin; measured 43k+ bars missing across 265 symbols since
    2016). Flipping the filter only fixes tomorrow — the updater appends days after `end` and can
    never reach backwards — so the history rides in on scripts/bz_backfill.json.gz, built by
    scripts/build_bz_backfill.py straight from NSE's own daily bhavcopies. DATA_RUNBOOK §80.

    Each block also carries `pre`: the factor needed to UNDO a phantom corporate action. When a stock
    was promoted back out of BZ the daily append saw one huge ratio across the invisible hole and
    ca_factor() divided it out as a split — 21 symbols measured, none with any official action on
    NSE's corporate-action feed (ATLASCYCLE x2/3, AHLWEST x1/2, GVKPIL x2, SUPREMEENG x6, ...).
    `pre` is scoped to [`from`, `after`], ONE segment, because a symbol with two holes carries a
    different phantom product on each (A = p1*p2, B = p2, C = 1) — applying it series-wide would
    fix the near segment and break the far one.

    Idempotent: a block whose first bar is already present is skipped whole, so `pre` can never be
    applied twice, and a from-scratch rebuild (which now ingests BZ itself) no-ops every block.
    Returns bars inserted."""
    import bisect

    lp = os.path.join(HERE, "bz_backfill.json.gz")
    if not os.path.exists(lp):
        return 0
    try:
        led = json.load(gzip.open(lp, "rt", encoding="utf-8"))
    except Exception as ex:
        print(f"  bz_backfill ledger unreadable ({ex}) — skipped")
        return 0
    total = scaled = skipped = 0
    for sym, blocks in (led.get("blocks") or {}).items():
        e = data.get(sym)
        if not e or not e.get("d"):
            continue
        if any(k not in e for k in ("c", "t", "h", "l", "op", "v", "dv", "vw")):
            continue
        for b in sorted(blocks, key=lambda x: x["after"]):
            bars = b.get("bars") or []
            if not bars:
                continue
            ds = e["d"]
            i = bisect.bisect_left(ds, bars[0][0])
            if i < len(ds) and ds[i] == bars[0][0]:
                continue  # already applied — zero-cost steady state
            j = bisect.bisect_left(ds, b["after"])
            if not (j < len(ds) and ds[j] == b["after"]):
                skipped += 1
                continue  # anchor bar gone (rename/merge) — don't guess
            pre = float(b.get("pre") or 1.0)
            if abs(pre - 1.0) > 1e-9:
                # (`from`, `after`] — bisect_RIGHT, because `from` is the previous block's LAST
                # inserted bar, which already sits at the right scale. bisect_left would drag that
                # bar into this segment and scale it twice.
                lo = bisect.bisect_right(ds, int(b.get("from") or 0))
                for key in ("c", "h", "l", "op", "vw"):
                    if key in e:
                        e[key][lo : j + 1] = [round(x * pre, 2) for x in e[key][lo : j + 1]]
                scaled += 1
                print(
                    "  BZ-BACKFILL %s: undid a phantom corporate action x%.4f on bars %d..%d"
                    % (sym, pre, ds[lo], ds[j])
                )
            at = j + 1
            for k, (ymd, c, t, h, l, op, v, dv, vw) in enumerate(bars):
                p = at + k
                e["d"].insert(p, ymd)
                e["c"].insert(p, c)
                e["t"].insert(p, t)
                e["h"].insert(p, h)
                e["l"].insert(p, l)
                e["op"].insert(p, op)
                e["v"].insert(p, int(v))
                e["dv"].insert(p, dv)
                e["vw"].insert(p, vw)
            total += len(bars)
    if total:
        print(
            "BZ backfill: %d bars spliced in (%d phantom CAs undone, %d blocks skipped), ledger built %s"
            % (total, scaled, skipped, led.get("built"))
        )
    return total


def apply_series_surgery(data, meta):
    """Wrong-company stitch repair (scripts/dvl_dtil_surgery.json.gz, DATA_RUNBOOK §89).

    The NSE ticker DTIL was RECYCLED: today's DVL traded as DTIL until 2010-07-26
    (DTIL->DPTL->DPL->DVL), and the tea company demerged out of it listed FRESH as DTIL on
    2015-01-20 (different ISIN, a different company). build_sf_data's symchg.csv supplement had
    no recycled-ticker guard, so the 2026-08-02 full rebuild funneled the tea company's whole
    bhavcopy history into DVL; the same-day dedup keeps the higher-close row, making bin DVL
    2015-2023 a two-company chimera (measured vs MTO volume identity) and leaving DTIL a 7-bar
    stub. The fake ~2x "moves" where the chain switched company also fed ca_factor(), and on
    2021-08-05 the live updater applied a 1:2 bonus factor that reconciled against the TEA
    company's ex-drop — NSE's CA feed mis-keys that bonus under DVL (§89e; the true DVL tape has
    no CA-sized move anywhere 2015->date). Net: the surviving pre-2015 history sits at a
    measured 0.7118x raw when the whole true DVL series is simply RAW.

    The ledger carries bhavcopy-true replacement bars for both symbols plus a one-shot `pre`
    factor that rescales the kept pre-2015 DVL bars onto the right adjustment level. Idempotent:
    the stored segment is compared to the ledger segment and everything (including `pre`) is
    skipped when they already match; `pre` is additionally gated on an anchor bar still holding
    its recorded WRONG close, so a future clean rebuild can never be double-scaled. Bars the
    daily updater appended after the ledger was built are preserved untouched."""
    import bisect

    lp = os.path.join(HERE, "dvl_dtil_surgery.json.gz")
    if not os.path.exists(lp):
        return 0
    try:
        led = json.load(gzip.open(lp, "rt", encoding="utf-8"))
    except Exception as ex:
        print(f"  series-surgery ledger unreadable ({ex}) — skipped")
        return 0
    KEYS = ("d", "c", "t", "h", "l", "op", "v", "dv", "vw")
    changed = 0
    jobs = [(sym, spec, False) for sym, spec in (led.get("replace") or {}).items()] + [
        (sym, spec, True) for sym, spec in (led.get("create") or {}).items()
    ]
    for sym, spec, is_create in jobs:
        bars = spec.get("bars") or []
        if not bars:
            continue
        frm = int(spec.get("from") or bars[0][0])
        e = data.get(sym)
        if e is None:
            if not is_create:
                print(f"  SURGERY {sym}: series absent — replace skipped")
                continue
            data[sym] = e = {k: [] for k in KEYS}
        i0 = bisect.bisect_left(e["d"], frm)
        i1 = bisect.bisect_right(e["d"], bars[-1][0])
        cur_seg = [[e[k][i] for k in KEYS] for i in range(i0, i1)]
        new_seg = [list(b) for b in bars]
        if cur_seg == new_seg:
            continue  # steady state — zero-cost no-op
        pre = float(spec.get("pre") or 1.0)
        if abs(pre - 1.0) > 1e-9 and i0 > 0:
            anc = spec.get("pre_anchor") or {}
            ai = bisect.bisect_left(e["d"], int(anc.get("ymd") or 0))
            ok = (
                ai < i0
                and e["d"][ai] == int(anc.get("ymd") or 0)
                and anc.get("c")
                and abs(e["c"][ai] / anc["c"] - 1) < 0.005
            )
            if ok:
                for key in ("c", "h", "l", "op", "vw"):
                    e[key][:i0] = [round(x * pre, 2) for x in e[key][:i0]]
                print("  SURGERY %s: pre-%d history rescaled x%.6f onto the official CA level" % (sym, frm, pre))
            else:
                print(
                    f"  SURGERY {sym}: pre-anchor {anc} no longer matches — prescale skipped "
                    "(history already on a different level; verify by hand)"
                )
        kept_tail = len(e["d"]) - i1
        for ki, key in enumerate(KEYS):
            e[key][i0:i1] = [b[ki] for b in new_seg]
        changed += len(new_seg)
        lm = spec.get("meta") or {}
        m = meta.get(sym)
        if lm and (m is None or m.get("name") in (None, sym) or not m.get("isin")):
            mm = meta.setdefault(sym, {})
            for k2, v2 in lm.items():
                mm[k2] = v2
            mm.setdefault("raw", bars[-1][1])
        print(
            "  SURGERY %s: %d ledger bars %d..%d spliced (%d replaced, %d later-appended kept)"
            % (sym, len(new_seg), new_seg[0][0], new_seg[-1][0], len(cur_seg), kept_tail)
        )
    return changed


def main():
    if os.path.exists(MARK):
        os.remove(MARK)
    if "--base" in sys.argv:
        base_path = sys.argv[sys.argv.index("--base") + 1]
        print(f"Base: local file {base_path}")
        D = json.loads(gzip.decompress(open(base_path, "rb").read()))
    else:
        D = load_base()
    last = datetime.datetime.strptime(D["end"], "%Y-%m-%d").date()
    today = datetime.date.today()
    days = []
    d = last + datetime.timedelta(days=1)
    while d <= today:
        # ALL calendar days — weekends included. Budget Saturdays (2025-02-01), weekend muhurat
        # sessions and DR-drill Saturdays are real trading days with a published bhavcopy; the old
        # weekday()<5 filter silently dropped them (52w hi/lo were provably wrong for 55-147 stocks
        # after each budget Saturday). A non-session weekend costs one "no file" skip, nothing more;
        # the duplicate-of-previous-day guard below catches NSE's holiday URL misdirect.
        days.append(d)
        d += datetime.timedelta(days=1)
    # NOTE: do NOT early-return when there are no new days — self_heal (below) must still run so phantom-CA
    # corrections (e.g. REC) get applied + republished even on an "up to date" day. The append loop simply
    # iterates an empty list, and the write/publish path already handles the heal-only case (`healed`).
    if days:
        print("Missing trading-day candidates: {}".format(", ".join(x.isoformat() for x in days)))
    else:
        print("No new trading days (end={}) — running self-heal pass only.".format(D["end"]))

    data = D["data"]
    meta = D["meta"]
    j = B.jar()
    appended = 0
    # OFFICIAL split/bonus ratios (refreshed by build_corp_actions.py in the workflow). Applied
    # exactly on the ex-date so a split/bonus with an ex-date price move (or a small bonus whose
    # drop stays inside [0.75,1.30]) is adjusted correctly instead of mis-inferred from the drop.
    try:
        _ca = json.load(open(os.path.join(HERE, "corp_actions.json")))
        CA_OFF = {s: {int(e[0]): e[1] for e in v} for s, v in _ca.get("factors", {}).items()}
        NOADJ = {s: set(v) for s, v in _ca.get("noadjust", {}).items()}
    except Exception as ex:
        CA_OFF = {}
        NOADJ = {}
        print(f"  (corp_actions.json unavailable: {ex} — inference only)")
    # ISIN -> current ticker. When a NEW ticker appears carrying the same ISIN as an existing series,
    # it's a rename (same security) -> migrate the history onto the new ticker instead of starting a
    # fresh, truncated series (which would break 52w hi/lo etc. for ~a year). Same logic the full
    # build uses; this keeps future renames continuous between rebuilds.
    isin2sym = {meta[s]["isin"]: s for s in data if isinstance(meta.get(s), dict) and meta[s].get("isin")}
    # One-time format migration: old bins store per-mil offsets (hb/lb/ob/vw) + delivery x10; the
    # new format stores EXACT h/l/op/vw + delivery %. Convert on load so this updater works on either
    # (a freshly-rebuilt exact bin already has 'h' and is skipped).
    for e in data.values():
        if "h" not in e and "hb" in e:
            c = e["c"]
            n = len(c)
            hb = e.get("hb", [0] * n)
            lb = e.get("lb", [0] * n)
            ob = e.get("ob", [0] * n)
            vwo = e.get("vw", [0] * n)
            e["h"] = [round(c[i] * (1000 + hb[i]) / 1000, 2) for i in range(n)]
            e["l"] = [round(c[i] * (1000 - lb[i]) / 1000, 2) for i in range(n)]
            e["op"] = [round(c[i] * (1000 + ob[i]) / 1000, 2) for i in range(n)]
            e["vw"] = [round(c[i] * (1000 + vwo[i]) / 1000, 2) for i in range(n)]
            e["dv"] = [round(x / 10, 2) for x in e.get("dv", [])]
            for kk in ("hb", "lb", "ob"):
                e.pop(kk, None)
    # Delivery-% heal ledgers (scripts/dv_fill.json + dv_fill_hist.json.gz): recovered DELIV_PER
    # cells, BE/T2T '-' days (compulsory delivery -> 100), and the 2002-2019 MTO-file backfill
    # (pre-2020 bhavcopies have no DELIV_PER column). Fill-only where dv==0, so a re-run applies
    # 0 and is a no-op; a non-zero count flags a real change and rides the publish condition below.
    dvf = B.apply_dv_fill(data)
    # §88b one-shot OVERWRITE leg (scripts/dv_overwrite.json): the 602 DVL cells the 2026-08-02 MTO
    # backfill keyed to the WRONG COMPANY carry dv>0, which fill-only can never correct. Guarded on
    # the bar still matching BOTH stored anchors (old dv AND the adjudicating MTO volume), so once
    # every cell reads its corrected value this is a permanent no-op and publishes nothing.
    dvo = B.apply_dv_overwrite(data)
    # MANUAL rename merges the ISIN-detector can't make: same security, but the ISIN CHANGED at the
    # rename so the ISIN-based auto-merge skips it (a safety guard against recycled tickers). These are
    # verified price-continuous. Idempotent: once the old series is folded in and dropped it's a no-op.
    # {new_current_ticker: old_predecessor}. IBC-relisted / renamed securities whose ISIN CHANGED at the
    # rename (RUCHISOYA->RUCHI post-IBC->PATANJALI; Burger King India->Restaurant Brands Asia).
    MANUAL_MERGE = {
        "PCBL": "PHILIPCARB",  # INE602A01023 -> INE602A01031 (Jan 2022, prices continuous)
        "PATANJALI": "RUCHI",  # Ruchi Soya relisted as RUCHI (2020-01) -> PATANJALI (2022-07); ISIN changed at IBC
        "RBA": "BURGERKING",  # Burger King India -> Restaurant Brands Asia (2022-02)
        "LTM": "LTIM",  # L&T Infotech (LTIM series 2016-2022) -> LTIMindtree (LTM 2022-12);
        # Nifty-500 membership + fundamentals use LTM, so the pre-2022 price
        # history (under LTIM) was orphaned -> LTM missing 2020-2022. Prices
        # continuous at the join (5065.75 -> 4975.40, no split); no LTM CAs.
        "GUJENERGY": "GUJGASLTD",  # Gujarat Gas -> Gujarat Energy Ltd, symbol change eff 2026-07-01 (NSE
        # symbolchange.csv). ISIN INE844O01030 UNCHANGED, but the Jul-1 bhavcopy row
        # carried no ISIN so the stub was created isin-less and the auto-merge never
        # fired. Prices continuous at the join (327.05 -> 340.00, no ratio); the -12%
        # 2026-07-02 scheme-demerger ex-date is kept via NSE noadjust, and the 2019
        # split factor now keyed under GUJENERGY has ex < join, so adj stays 1.
        # --- rest of the 2026-07 tripwire batch (same ISIN-less day-one stub disease, ISINs
        # unchanged per EQUITY_L). All verified: official symbolchange.csv pair + price-continuous
        # join (ratio 0.95-1.05, no split-like jump) + no official CAs on the new tickers (adj=1).
        "ONIDA": "MIRCELECTR",  # Mirc Electronics -> Onida Electronics (2026-06-19; 38.22 -> 40.10)
        "AURUS": "LYPSAGEMS",  # Lypsa Gems -> Aurus Gem Corporation (2026-07-14; 4.63 -> 4.41)
        # Axis MF's 9 ETF ticker renames of 2026-07-03 (NAV-continuous at the join):
        "ITAXIS": "AXISTECETF",
        "NIFTYAXIS": "AXISNIFTY",
        "BNKETFAXIS": "AXISBNKETF",
        "HEALTHAXIS": "AXISHCETF",
        "CONSUMAXIS": "AXISCETF",
        "SENSEXAXIS": "AXSENSEX",
        "GOLDAXIS": "AXISGOLD",
        "VALUEAXIS": "AXISVALUE",
        "SILVERAXIS": "AXISILVER",
        # --- 2026-08-11 orphaned-series batch: old-key HISTORY FRAGMENTS stranded by
        # historical renames (census of all 1,705 dead-ending series; each pair is in
        # scripts/_rename_map.json AND measured price-continuous at the join on the new
        # key's adjusted scale: drift = new_first / (old_last_real x CA-adj) in 0.93-1.07,
        # gap <= 78d, weekend-special residue bars excluded from the old end. Old keys
        # hold NO live fundamentals rows and are absent from F&O history (verified).
        # Without the merge each old key dies mid-history and marks -100% in backtests.
        "ADOR": "ADORWELD",  # Ador Welding pre-2004 fragment (drift 1.058, 3d)
        "JSWDULUX": "AKZOINDIA",  # ICI/Akzo era pre-2010 fragment (drift 1.000, 1d)
        "SUNDROP": "ATFL",  # Agro Tech Foods pre-2003 (drift 1.014, 2d)
        "BANKADD": "BANKETFADD",  # DSP Bank ETF rename chain 2024 (drift 1.004, 1d)
        "SUDARCOLOR": "CLNINDIA",  # Colour-Chem/Clariant pre-2006 (drift 1.073, 3d)
        "LANDSMILL": "EXCEL",  # Excel Realty pre-2015 (drift 0.955 after 0.022 CA-adj)
        "SCHAEFFLER": "FAGBEARING",  # FAG Bearings pre-2001 (drift 1.009 after 0.2 CA-adj)
        "GVPIL": "GEPIL",  # GE Power pre-2016 fragment (drift 0.974, 2d)
        "GVT&D": "GET&D",  # GE T&D pre-2016 fragment (drift 1.009, 2d)
        "GOLDADD": "GOLDETFADD",  # DSP Gold ETF rename chain 2024 (drift 1.002, 1d)
        "BIRLANU": "HIL",  # Hyderabad Inds pre-2012 fragment (drift 0.983, 1d)
        "STYRENIX": "INEOSSTYRO",  # Styrolution/INEOS pre-2016 (drift 1.024, 3d)
        "ITADD": "ITETFADD",  # DSP IT ETF rename chain 2024 (drift 1.008, 1d)
        "BOSCH-HCIL": "JCHAC",  # Johnson Controls-Hitachi pre-2016 (drift 0.983, 3d)
        "SUMMIT": "KECINFRA",  # KEC Infrastructures pre-2006 (drift 0.959, 1d)
        "CIEINDIA": "MAHINDCIE",  # Mahindra CIE pre-2013 fragment (drift 1.013, 1d)
        "NIFTYADD": "NIFTY50ADD",  # DSP Nifty ETF rename chain 2024 (drift 1.008, 1d)
        "PROZONER": "PROZONINTU",  # Prozone pre-2014 fragment (drift 0.956, 6d)
        "TRANSWORLD": "SHREYAS",  # Shreyas Shipping pre-2006 era (drift 0.974, 3d)
        "SMLMAH": "SMLISUZU",  # SML Isuzu pre-2011 fragment (drift 1.002, 3d)
        "TTML": "TATATELSER",  # Tata Tele (M) pre-2003 fragment (drift 0.960, 1d)
        "XLENERGY": "XLTELENE",  # XL Telecom pre-2009 fragment (drift 0.950, 1d)
        "IBULLSLTD": "YAARI",
    }  # Yaari Digital 2013-2020 fragment (drift 0.927, 1d)
    # --- 2026-08-23 ISIN-SEAM batch (DATA_RUNBOOK §95g's open queue, landed in §105): the 103 seams
    # the issuer-prefix sweep CONFIRMED as one company (scripts/_isin_seam_verdicts.json) were never
    # stitched because the ISIN CHANGED at each seam (face-value change, scheme) — the auto-merge must
    # refuse that. Each entry carries the SEAM factor NSE itself states: PREVCLOSE printed on the new
    # symbol's first session / the old symbol's last close (exact to the paise), applied ON TOP of the
    # new key's own later official factors (the CA-adj loop below). Landed only where the join is then
    # continuous on the bin: drift = stored_new_first / (stored_old_last x seam x CA-adj) in [0.85,1.15]
    # and gap <= 120d — 31 of 103. The other 71 (relistings with a nominal first prevclose, IBC capital
    # reductions, unexplained steps such as PROVOGUE 0.48) stay SPLIT: joining them would hand
    # retPctAt a stale base across the hole and mint a fake return; build_membership_v2's era-aware
    # key emission makes those companies visible under the old key instead. Verified no live
    # fundamentals rows under any old key here (FUND_ALIAS already bridges them, §95f).
    # Value form {"old": OLD, "seam": f} is accepted alongside the plain "OLD" string.
    SEAM_MERGES = {
        "ARVINDREM": {
            "old": "ARL",
            "seam": 10,
        },  # ARL 20120511→20120608: NSE prevclose 23.5/close 2.35; CA-adj 1, drift 0.994, gap 28d, 2319 bars
        "ASHCONIUL": {
            "old": "ASHCO",
            "seam": 10,
        },  # ASHCO 20100920→20101004: NSE prevclose 7.5/close 0.75; CA-adj 1, drift 1.067, gap 14d, 713 bars
        "ASIANHOTNR": {
            "old": "ASIANHOTEL",
            "seam": 1,
        },  # ASIANHOTEL 20100223→20100407: NSE prevclose 559.95/close 559.95; CA-adj 1, drift 0.898, gap 43d, 2339 bars
        "AVANTIFEED": {
            "old": "AVANTI",
            "seam": 1.00197,
        },  # AVANTI 20150129→20150415: NSE prevclose 1805.0/close 1801.45; CA-adj 0.06667, drift 0.984, gap 76d, 1179 bars
        "BALLARPUR": {
            "old": "BILT",
            "seam": 0.2,
        },  # BILT 20080228→20080331: NSE prevclose 27.5/close 137.5; CA-adj 1, drift 1.011, gap 32d, 1861 bars
        "BELLCERATL": {
            "old": "BELCERAMIC",
            "seam": 3,
        },  # BELCERAMIC 20100723→20100908: NSE prevclose 25.95/close 8.65; CA-adj 1, drift 0.990, gap 47d, 2413 bars
        "BHAGYANGR": {
            "old": "BHAGYNAGAR",
            "seam": 1,
        },  # BHAGYNAGAR 20170309→20170517: NSE prevclose 24.35/close 24.35; CA-adj 1, drift 1.092, gap 69d, 3509 bars
        "CASTROLIND": {
            "old": "CASTROL",
            "seam": 1,
        },  # CASTROL 20140226→20140314: NSE prevclose 287.7/close 287.7; CA-adj 0.5, drift 1.041, gap 16d, 2259 bars
        "CENTUM": {
            "old": "SOLECTCENT",
            "seam": 0.69905,
        },  # SOLECTCENT 20070807→20071005: NSE prevclose 195.0/close 278.95; CA-adj 1, drift 1.082, gap 59d, 979 bars
        "COLPAL": {
            "old": "COLGATE",
            "seam": 1,
        },  # COLGATE 20071128→20071217: NSE prevclose 382.1/close 382.1; CA-adj 0.5, drift 1.016, gap 19d, 1798 bars
        "DSSL": {
            "old": "DYNASYS",
            "seam": 10,
        },  # DYNASYS 20111102→20111201: NSE prevclose 9.0/close 0.9; CA-adj 1, drift 0.900, gap 29d, 134 bars
        "ESSENTIA": {
            "old": "INTEGRA",
            "seam": 1,
        },  # INTEGRA 20220228→20220314: NSE prevclose 1.7/close 1.7; CA-adj 0.5, drift 0.918, gap 14d, 954 bars
        "GBGLOBAL": {
            "old": "MANDHANA",
            "seam": 1,
        },  # MANDHANA 20190213→20190607: NSE prevclose 2.35/close 2.35; CA-adj 1, drift 1.043, gap 114d, 2155 bars
        "GOCLCORP": {
            "old": "GULFOILCOR",
            "seam": 1,
        },  # GULFOILCOR 20140603→20140626: NSE prevclose 164.6/close 164.6; CA-adj 1, drift 0.978, gap 23d, 1638 bars
        "HFCL": {
            "old": "HIMACHLFUT",
            "seam": 1,
        },  # HIMACHLFUT 20110207→20110309: NSE prevclose 9.4/close 9.4; CA-adj 1, drift 1.064, gap 30d, 2574 bars
        "HINDMOTORS": {
            "old": "HINDMOTOR",
            "seam": 1,
        },  # HINDMOTOR 20110125→20110221: NSE prevclose 20.05/close 20.05; CA-adj 1, drift 0.915, gap 27d, 2566 bars
        "LGBBROSLTD": {
            "old": "LGBROS",
            "seam": 10,
        },  # LGBROS 20100312→20100330: NSE prevclose 227.5/close 22.75; CA-adj 0.25, drift 1.072, gap 18d, 2328 bars
        "MORARJEE": {
            "old": "MORARJETEX",
            "seam": 1,
        },  # MORARJETEX 20120810→20120918: NSE prevclose 11.95/close 11.95; CA-adj 1, drift 1.054, gap 39d, 1036 bars
        "NCOPPER": {
            "old": "NISSAN",
            "seam": 10,
        },  # NISSAN 20110928→20111017: NSE prevclose 22.5/close 2.25; CA-adj 1, drift 1.129, gap 19d, 1164 bars
        "NDL": {
            "old": "NANDAN",
            "seam": 10,
        },  # NANDAN 20120306→20120323: NSE prevclose 23.0/close 2.3; CA-adj 0.03333, drift 1.070, gap 17d, 1524 bars
        "NTL": {
            "old": "SUJANATOW",
            "seam": 10,
        },  # SUJANATOW 20130806→20130911: NSE prevclose 9.5/close 0.95; CA-adj 1, drift 0.953, gap 36d, 1188 bars
        "ORTINGLOBE": {
            "old": "ORTINLABSS",
            "seam": 1,
        },  # ORTINLABSS 20210111→20210330: NSE prevclose 31.0/close 31.0; CA-adj 1, drift 1.048, gap 78d, 1334 bars
        "PAISALO": {
            "old": "SEINVEST",
            "seam": 10,
        },  # SEINVEST 20111003→20111017: NSE prevclose 101.0/close 10.1; CA-adj 0.05, drift 0.954, gap 14d, 567 bars
        "PALREDTEC": {
            "old": "PALREDTECH",
            "seam": 2,
        },  # PALREDTECH 20160425→20160509: NSE prevclose 121.9/close 60.95; CA-adj 1, drift 0.954, gap 14d, 133 bars
        "RMMIL": {
            "old": "RESURGERE",
            "seam": 10,
        },  # RESURGERE 20120613→20120627: NSE prevclose 2.0/close 0.2; CA-adj 1, drift 1.000, gap 14d, 927 bars
        "SHIVATEX": {
            "old": "SHIVTEX",
            "seam": 1,
        },  # SHIVTEX 20171102→20171226: NSE prevclose 401.4/close 401.4; CA-adj 1, drift 1.138, gap 54d, 3976 bars
        "SIGNET": {
            "old": "SIGNETIND",
            "seam": 1.12671,
        },  # SIGNETIND 20150129→20150313: NSE prevclose 127.6/close 113.25; CA-adj 0.1, drift 0.956, gap 43d, 657 bars   # CHAIN: must run before SIGIND<-SIGNET below (older seam first)
        "SIGIND": {
            "old": "SIGNET",
            "seam": 10,
        },  # SIGNET 20180810→20180829: NSE prevclose 65.0/close 6.5; CA-adj 1, drift 1.000, gap 19d, 838 bars
        "SPLPETRO": {
            "old": "SUPPETRO",
            "seam": 1,
        },  # SUPPETRO 20220406→20220524: NSE prevclose 921.3/close 921.3; CA-adj 0.5, drift 0.918, gap 48d, 5336 bars
        "SUBEXLTD": {
            "old": "SUBEX",
            "seam": 1,
        },  # SUBEX 20201021→20201105: NSE prevclose 16.95/close 16.95; CA-adj 1, drift 1.103, gap 15d, 4240 bars
        "TVSHLTD": {
            "old": "SUNCLAYTON",
            "seam": 1,
        },  # SUNCLAYTON 20120906→20121023: NSE prevclose 185.45/close 185.45; CA-adj 1, drift 1.084, gap 47d, 1034 bars
    }
    MANUAL_MERGE.update(SEAM_MERGES)
    merged = 0
    for new, spec in MANUAL_MERGE.items():
        old = spec["old"] if isinstance(spec, dict) else spec
        seam = float(spec.get("seam", 1.0)) if isinstance(spec, dict) else 1.0
        on = data.get(new)
        oo = data.get(old)
        if on and oo and on["d"] and oo["d"] and oo["d"][0] < on["d"][0]:
            idx = [i for i, dd in enumerate(oo["d"]) if dd < on["d"][0]]
            if idx:
                # The old series is stored RAW; the new series is already split/bonus-adjusted. Apply any
                # of `new`'s official factors whose ex-date is AFTER the old series ended, so the prepended
                # prices land on the SAME adjusted scale (else a ratio-3 discontinuity at the join, e.g.
                # PATANJALI's 2025-09 1:2 bonus f=0.3333 must scale RUCHI's 2020-22 prices down /3).
                # SEAM_MERGES additionally carry NSE's own seam factor (face-value change at the rename).
                oldend = oo["d"][idx[-1]]
                adj = seam
                for ex, f in CA_OFF.get(new, {}).items():
                    if ex > oldend:
                        adj *= f
                for f in ("d", "c", "t", "h", "l", "op", "v", "dv", "vw"):
                    if f in oo and f in on:
                        if adj != 1.0 and f in ("c", "h", "l", "op", "vw"):
                            on[f] = [round(oo[f][i] * adj, 2) for i in idx] + on[f]
                        else:
                            on[f] = [oo[f][i] for i in idx] + on[f]
                # The new ticker's stub meta is a placeholder (name=symbol, ind=Unknown, often no ISIN —
                # that missing ISIN is usually WHY the auto-merge couldn't fire). Carry the predecessor's
                # company attributes over so the merged series keeps its industry/ISIN (ISIN only when the
                # stub has none: verified unchanged for GUJENERGY vs EQUITY_L; changed-ISIN pairs like
                # PATANJALI already carry their new ISIN from the daily appends, so this never clobbers).
                om = meta.get(old) or {}
                nm = meta.setdefault(new, {})
                if nm.get("name") in (None, new) and om.get("name"):
                    nm["name"] = om["name"]
                if nm.get("ind") in (None, "Unknown") and om.get("ind"):
                    nm["ind"] = om["ind"]
                if not nm.get("isin") and om.get("isin"):
                    nm["isin"] = om["isin"]
                # repoint the ISIN index at the survivor so same-ISIN auto-merge protection covers
                # any FUTURE rename of this security within the same run (the index was built from
                # pre-merge meta and would otherwise still point at the just-deleted old symbol)
                if nm.get("isin"):
                    isin2sym[nm["isin"]] = new
                data.pop(old, None)
                meta.pop(old, None)
                merged += 1
                print("  MANUAL RENAME MERGE %s -> %s (%d pts prepended, adj=%.4f)" % (old, new, len(idx), adj))
    # BEFORE anything that reads a bar's neighbours: the series-BZ history our old ("EQ","BE") filter
    # dropped. Runs after MANUAL_MERGE so the ledger's current tickers are already consolidated, and
    # before the day loop because appending today's BZ row onto a years-stale series would hand
    # ca_factor() a multi-year ratio to mis-read as a split (measured: HDIL 1.57/2.20 -> "3/4",
    # RAJESHEXPO 83.58/223.97 -> "2/5", both phantom).
    bz = insert_bz_history(data)
    sg = apply_series_surgery(data, meta)  # wrong-company stitch repair (DVL/DTIL, §89) — before the
    # day loop so appends land on the repaired series
    mr = apply_manual_rights(data)  # hand-verified per-stock rights adjustments to match Trendlyne
    ao = apply_ca_arbitrated(
        data
    )  # official splits the close-ratio guard rejected, confirmed by the ex-day OPEN (§87g)
    if ao:
        print("Open-arbitrated corporate actions: %d applied." % ao)
    wk = insert_weekend_sessions(
        data, j, {(o["old"] if isinstance(o, dict) else o): n for n, o in MANUAL_MERGE.items()}
    )  # backfill missing weekend special sessions (budget Sats etc.); old->new so merged-away tickers' sessions land on the survivor
    if wk:
        print("Weekend special sessions: %d bars inserted." % wk)
    for day in days:
        rows = B.fetch_day(day, j)
        if not rows:
            print(f"  {day}: no file (holiday or not yet published)")
            continue
        # stale-file guard: NSE sometimes serves the prior day's file — if almost every
        # symbol's close equals its current last close, this is a duplicate; skip it.
        same = tot = 0
        for r in rows:
            o = data.get(r[0])
            if o and o["c"]:
                tot += 1
                if abs(o["c"][-1] - r[1]) < 0.005:
                    same += 1
        if tot > 500 and same / tot > 0.99:
            print("  %s: duplicate of previous day (%d/%d identical) — skipped" % (day, same, tot))
            continue

        ymd = int(day.strftime("%Y%m%d"))
        for r in rows:
            sym, c, _p, t = r[0], r[1], r[2], r[3]
            h = r[4] if len(r) > 4 else c
            l = r[5] if len(r) > 5 else c
            o_ = r[6] if len(r) > 6 else c
            v = r[7] if len(r) > 7 else 0
            dlv = r[8] if len(r) > 8 else 0
            vw = r[9] if len(r) > 9 else 0
            hi = round(max(h, c), 2)
            lo_ = round(min(l, c) if l > 0 else c, 2)  # EXACT intraday hi/lo
            opx = round(o_, 2) if o_ > 0 else round(c, 2)
            vwx = round(vw, 2) if vw > 0 else round(c, 2)
            dvx = round(dlv, 2) if dlv else 0
            e = data.get(sym)
            if e is None:
                isin = r[11] if len(r) > 11 and r[11] else ""
                old = isin2sym.get(isin) if isin else None
                if old and old in data and old != sym and data[old]["d"] and data[old]["d"][-1] < ymd:
                    # same ISIN as an existing older series -> ticker RENAME: migrate the history
                    data[sym] = data.pop(old)
                    meta[sym] = meta.pop(old) if old in meta else {}
                    meta[sym]["isin"] = isin
                    isin2sym[isin] = sym
                    print(f"  {day}: RENAME {old} -> {sym} (ISIN {isin}) — history migrated")
                    e = data[sym]  # fall through to append today's row onto the migrated series
                else:  # genuine new listing (IPO / relist) — fresh series
                    data[sym] = {
                        "d": [ymd],
                        "c": [round(c, 2)],
                        "t": [round(t, 1)],
                        "h": [hi],
                        "l": [lo_],
                        "op": [opx],
                        "v": [int(v)],
                        "dv": [dvx],
                        "vw": [vwx],
                    }
                    meta.setdefault(sym, {"name": sym, "ind": "Unknown", "alive": True})
                    if isin:
                        meta[sym]["isin"] = isin
                        isin2sym[isin] = sym
                    continue
            if e["d"] and e["d"][-1] >= ymd:
                continue  # already have this day
            prev_raw = e["c"][-1]  # series is re-anchored: last value == last RAW close
            ratio = (c / prev_raw) if prev_raw else 1.0
            off = (CA_OFF.get(sym) or {}).get(ymd)  # OFFICIAL split/bonus factor for this ex-date
            nd = NOADJ.get(sym)  # official demerger/scheme ex-dates
            if off is not None and 0.75 <= (ratio / off) <= 1.30:
                f = off  # official split/bonus: divide out the exact ratio
            elif nd and not (0.75 <= ratio <= 1.30) and any(ymd - 3 <= e <= ymd for e in nd):
                # official demerger/scheme: real value left the stock -> keep the drop as a genuine move
                print(f"  {day}: {sym} demerger/scheme drop ratio={ratio:.3f} kept (not divided out)")
                f = 1.0
            else:
                f = ca_factor(ratio)
            if f != 1.0:  # corporate action: re-anchor history (prices scale by f; dv % does not)
                for key in ("c", "h", "l", "op", "vw"):
                    if key in e:
                        e[key] = [round(x * f, 2) for x in e[key]]
                print(
                    "  {}: {} corporate action f={}{} (history re-anchored)".format(
                        day, sym, f, " [official]" if off is not None and f == off else ""
                    )
                )
            e["d"].append(ymd)
            e["c"].append(round(c, 2))
            e["t"].append(round(t, 1))
            e["h"].append(hi)
            e["l"].append(lo_)
            e["op"].append(opx)
            e["v"].append(int(v))
            e["dv"].append(dvx)
            e["vw"].append(vwx)
            if sym in meta:
                meta[sym]["raw"] = round(c, 2)
        D["end"] = day.isoformat()
        appended += 1
        print("  %s: appended %d rows" % (day, len(rows)))

    # Belt-and-suspenders: re-check the last ~4 weeks of official actions and fix any that an
    # earlier run mis-handled (action published after its ex-date was already processed).
    healed = self_heal(data, CA_OFF, NOADJ, int(D["end"].replace("-", "")), j)
    if healed:
        print("Self-heal corrected %d corporate action(s)." % healed)

    # LAST, so it also catches bars appended/inserted THIS run: one turnover unit (₹ lacs) across
    # the whole file. NSE's old zip served raw rupees and still does on stray days (2022-08-08),
    # which silently disabled every turnover FLOOR before 2020. Idempotent — a converged file
    # reports 0. See runbook §88a.
    tunits = normalize_turnover_units(data)
    if tunits:
        print("Turnover units: normalised %d bar(s) rupees -> lacs." % tunits)

    # ALSO last: let `alive` DECAY. It is only ever (re)derived by a full build_sf_data run or
    # patch_sf_alive.py, so between rebuilds a symbol whose tape stops keeps alive=True for ever —
    # that is how PUNJCOMMU, off the NSE tape since 2003-03-31, still read alive in 2026 (§94).
    # This pass only ever turns a STALE True off (never on): the updater has no listing oracle here,
    # and dash_slim — the one build_sf_data uses — is not one either (its NSE side is a subset of
    # the tape). A symbol that resumes trading gets its True back from the next full rebuild /
    # patch_sf_alive run. Idempotent: a converged file reports 0.
    dead = B.veto_stale_alive(data, meta, D["end"])
    if dead:
        print(
            "Aliveness: %d symbol(s) had no bar within %dd of %s -> alive=False."
            % (dead, B.ALIVE_RECENCY_DAYS, D["end"])
        )

    # Industry/name for DELISTED symbols. meta.ind is only ever derived from dash_slim's
    # CURRENTLY-LISTED universe, so a symbol that stopped trading keeps ind="Unknown", name=<symbol>
    # forever — a survivorship gap in the metadata that no amount of price work closes (2,008 of the
    # live bin's 4,445 symbols carry it). scripts/industry_fills.json holds BSE's own IndustryNew for
    # the ones that matter, in the same vocabulary. Applied HERE, in the nightly incremental, because
    # the full rebuild that would otherwise pick it up is a multi-hour bhavcopy fetch that does not
    # run on a schedule. ONE DIRECTION ONLY — it never overwrites an industry the universe supplied,
    # so a symbol that comes back to life takes its live classification straight back. Idempotent:
    # a converged file reports 0.
    try:
        _fills = (json.load(open(os.path.join(HERE, "industry_fills.json"))) or {}).get("fills") or {}
    except Exception as e:
        _fills = {}
        print(f"  (industry_fills unavailable: {e})")
    _n = 0
    for _s, _f in _fills.items():
        _m = meta.get(_s)
        if not isinstance(_m, dict):
            continue
        if _m.get("ind") in (None, "", "Unknown", "Other") and _f.get("industry"):
            _m["ind"] = _f["industry"]
            _n += 1
        if _m.get("name") in (None, "", _s) and _f.get("name"):
            _m["name"] = _f["name"]
    if _n:
        print("Industry fills: %d delisted symbol(s) classified from the ledger." % _n)
    # ⚠️ _n MUST be in the publish gate below. It was not on the first cut (2026-08-12) and the
    # consequence was silent and total: the 16:08 UTC run printed "Industry fills: 26 ... classified"
    # and then, because that day appended no bars, hit the no-op return, rewrote the bin INSIDE the
    # runner and published nothing. All 26 fills were computed and thrown away with the runner, and
    # the same thing would have happened every quiet day forever. A heal that is not in the
    # did-anything-change test is not a heal — it is a log line.

    # ALWAYS rewrite the freshly-loaded MERGED base to disk — even on a no-op run — so the split/publish
    # step never reads the stale, UN-merged in-repo copy (frozen at an old `end`, still carrying
    # ZOMATO/RUCHI/BURGERKING as separate stubs) and trip split_sf_data.py's ZOMATO/ETERNAL publish-guard.
    # That guard-abort is what made a 2nd (workflow_dispatch / auto-rerun) run of the same day fail on
    # loop. The .sf_updated MARK + version marker stay gated on a REAL change below, so a no-op run
    # refreshes the on-disk bin but does NOT publish the release, bump clients, or commit a marker.
    blob = gzip.compress(json.dumps(D, separators=(",", ":")).encode(), 6)
    open(OUT, "wb").write(blob)
    if (
        not appended
        and not healed
        and not merged
        and not mr
        and not ao
        and not dvf
        and not dvo
        and not wk
        and not bz
        and not sg
        and not tunits
        and not dead
        and not _n
    ):
        print(
            f"No new day / heal / merge / manual-rights / open-arbitrated CA / dv-fill / dv-overwrite / weekend-insert / BZ-backfill / series-surgery / turnover-unit fix / aliveness decay / industry fill — rewrote merged base to {OUT} ({len(blob) / 1048576:.2f} MB); nothing to publish."
        )
        return
    open(MARK, "w").write(D["end"])
    # tiny version marker — committed daily, lets the browser cache the big bin in IndexedDB
    # keyed to this `end` and skip re-downloading 80 MB until the data actually changes.
    json.dump({"end": D["end"]}, open(os.path.join(ROOT, "docs", "sf_meta.json"), "w"))
    print("Wrote {} ({:.2f} MB) + docs/sf_meta.json, end={}".format(OUT, len(blob) / 1048576, D["end"]))


if __name__ == "__main__":
    main()
