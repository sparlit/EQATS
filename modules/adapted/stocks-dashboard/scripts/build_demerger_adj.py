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
"""Build scripts/demerger_adj.json — per-demerger price-adjustment factors.

WHY: a demerger is not a loss — holders receive shares in the spun-off entity — but the raw
NSE tape keeps the ex-date value separation as a price fall, so every trailing-window factor
(ret6m, mdd6, d52, rangePos, ...) reads a spin-off as a crash for the following 6-12 months.
Proven cases (2026-08-03 StockView reconciliation): SKFINDIA 2025-10 ret6m read -45% when the
holder was ~flat (SKF ex 2025-10-15, -54.8%% "drop"); NMDC 2023-03 read -12.7%% vs +110%% real
(NMDC Steel ex 2022-10-27); same for RELIANCE/Jio-Fin, SANOFI, ITC Hotels, SIEMENS Energy,
RAYMOND Realty, ABFRL/ABLBL, TMPV CV/PV, VEDL 5-way. Splits/bonus/rights already adjust;
this ledger closes the demerger gap.

FACTOR = ex-date OPEN / PREV_CLOSE from the official NSE bhavcopy. On a demerger ex-date the
open IS the special pre-open session's discovered price — the exchange's own valuation of the
residual company. update_sf_data.self_heal scales each pre-ex price by this factor (same
mechanics as splits), so the artificial gap disappears while the ex-date's own intraday move
(close/open) is kept as a genuine return. The raw close ratio rides along as the idempotence /
reconciliation anchor, so CI never needs to refetch old bhavcopies.

SOURCE: the NSE corporates-corporateActions feed, subjects containing demerger/spin-off ONLY.
- Bare "scheme of arrangement" / "capital reduction" subjects are logged and SKIPPED: a capital
  reduction is a real shareholder loss and must keep its drop.
- NEVER source ex-dates from corp_actions.json's `noadjust` map — that merges the phantom-crash
  keep-drop list (ADANIENT Hindenburg, COVID crashes, ...) which must never be adjusted.
- Events carrying an official split/bonus factor within ±3 days are SKIPPED and logged (the
  open-gap would double-count the split leg) — resolve those by hand if one ever appears.

Incremental: (sym, ex) pairs already in the ledger are kept untouched; only new feed events
fetch a bhavcopy (cached in scripts/_bhav_cache). Cheap — safe to run daily after
build_corp_actions.py, before update_sf_data.py.
Run: python -X utf8 scripts/build_demerger_adj.py
"""
import datetime
import json
import os

import build_fundamentals as F
import build_sf_data as B

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "demerger_adj.json")

STRICT_KW = ("demerger", "de-merger", "de merger", "spin off", "spin-off", "spinoff")
LOGGED_KW = (
    "scheme of arrangement",
    "scheme of amalgamation",
    "composite scheme",
    "reduction of capital",
    "capital reduction",
)
MIN_GAP = 1.0  # §170d (user, 2026-09-26): NO materiality floor — the auction price IS the exchange's measurement, so
# every gap is adjusted (the old 0.98 "noise" floor skipped HINDUNILVR 2025's real 1.6% Kwality Wall's
# separation, ~7x HUL's typical 0.24% morning move). Only an open AT/ABOVE the previous close is
# skipped: a spin-off cannot add value to the parent.
MAX_GAP = 0.05  # sanity floor — a >95% "demerger" is a data error, inspect by hand


def iso2ymd(s):
    d = F.iso(s)
    return int(d) if d else None


def sweep_feed(jar):
    """All demerger/spin-off subject events from the official CA feed, 2016 -> today."""
    h = {"User-Agent": F.UA, "Accept": "application/json", "Referer": "https://www.nseindia.com/"}
    ev, logged = [], []
    for yr in range(2016, datetime.date.today().year + 1):
        url = (
            "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
            "&from_date=01-01-%d&to_date=31-12-%d" % (yr, yr)
        )
        try:
            d = json.loads(F._get(url, headers=h, jar=jar, timeout=40))
            rows = d if isinstance(d, list) else d.get("data", [])
        except Exception as e:
            print("  %d: feed fetch failed (%s)" % (yr, str(e)[:60]))
            continue
        n = 0
        for r in rows:
            subj = (r.get("subject") or r.get("purpose") or "").lower()
            sym, ex = r.get("symbol"), iso2ymd(r.get("exDate"))
            if not sym or not ex:
                continue
            if any(k in subj for k in STRICT_KW):
                ev.append((sym, ex))
                n += 1
            elif any(k in subj for k in LOGGED_KW):
                logged.append((sym, ex, subj[:70]))
        print("  %d: %d demerger/spin-off events" % (yr, n))
    return ev, logged


def main():
    jar = F.nse_jar()
    try:
        led = {(x[0], int(x[1])): x for x in json.load(open(OUT))}
    except Exception:
        led = {}
    try:
        rename = json.load(open(os.path.join(HERE, "_rename_map.json")))
    except Exception:
        rename = {}
    try:
        _ca = json.load(open(os.path.join(HERE, "corp_actions.json")))
        CA_OFF = {s: {int(e[0]) for e in v} for s, v in _ca.get("factors", {}).items()}
    except Exception:
        CA_OFF = {}

    ev, logged = sweep_feed(jar)
    # dedupe: one event per symbol per ~week (VEDL's 2026 demerger appears at 0430 AND 0501)
    ev.sort(key=lambda x: (x[0], x[1]))

    def od(y):
        return datetime.date(y // 10000, y // 100 % 100, y % 100).toordinal()

    dedup = []
    for sym, ex in ev:
        if dedup and dedup[-1][0] == sym and od(ex) - od(dedup[-1][1]) <= 7:
            continue
        dedup.append((sym, ex))
    print(
        "feed events: %d (%d after dedupe); logged-only scheme/cap-reduction: %d" % (len(ev), len(dedup), len(logged))
    )
    for s, e, t in logged:
        print("  LOGGED (not adjusted): %s %d  %s" % (s, e, t))

    added = 0
    for sym, ex in dedup:
        key_sym = rename.get(sym, sym)  # our merged series key = current name
        if (key_sym, ex) in led or (sym, ex) in led:
            continue
        if any(od(ex) - 3 <= od(x) <= od(ex) + 3 for x in CA_OFF.get(sym, set()) | CA_OFF.get(key_sym, set())):
            print(
                "  SKIP %s %d: official split/bonus within +-3d — open-gap would double-count; resolve by hand"
                % (sym, ex)
            )
            continue
        # resolve the actual ex TRADING day: first day on/after the feed ex-date with a bhavcopy row.
        # The feed reports the CURRENT symbol, but the bhavcopy that day used the name that traded
        # THEN (TMPV's 2025-10-14 ex-date bhavcopy row is TATAMOTORS) — try old names too.
        cands = {sym, key_sym, rename.get(sym, sym)} | {o for o, n in rename.items() if n in (sym, key_sym)}
        row = None
        used = None
        d = datetime.date(ex // 10000, ex // 100 % 100, ex % 100)
        for k in range(4):
            dd = d + datetime.timedelta(days=k)
            if dd > datetime.date.today():
                break
            rows = B.fetch_day(dd, jar)
            if not rows:
                continue
            row = next((r for r in rows if r[0] in cands), None)
            used = int(dd.strftime("%Y%m%d"))
            break  # first trading day decides — row or not
        if not row:
            print("  SKIP %s %d: no bhavcopy row on the ex trading day" % (sym, ex))
            continue
        if (key_sym, used) in led:  # a hand-verified row (DATA_RUNBOOK §170) already owns this bar — never overwrite it
            continue
        close, prev, opn = row[1], row[2], row[6]
        if not prev or not opn:
            print("  SKIP %s %d: missing open/prevclose in bhavcopy" % (sym, ex))
            continue
        factor, raw_drop = opn / prev, close / prev
        if factor >= MIN_GAP:
            print(
                "  SKIP %s %d: open-gap %.4f >= %.2f (opened at/above the previous close - no value separation)"
                % (sym, ex, factor, MIN_GAP)
            )
            continue
        if factor <= MAX_GAP:
            print("  SKIP %s %d: open-gap %.4f implausible — inspect by hand" % (sym, ex, factor))
            continue
        led[(key_sym, used)] = [key_sym, used, round(factor, 4), round(raw_drop, 4)]
        added += 1
        print(
            "  + %s ex %d  factor=%.4f (open %.2f / prev %.2f)  raw_drop=%.4f%s"
            % (key_sym, used, factor, opn, prev, raw_drop, "" if key_sym == sym else f"  [feed sym {sym}]")
        )

    # §170d (user, 2026-09-26): a spin-off NSE files only as "Scheme of Arrangement" (no demerger/spin-off wording) is never
    # auto-adjusted above — 59 such Nifty-500 events sat raw for years (DATA_RUNBOOK §170). Every RECENT (<= 30 days) scheme /
    # amalgamation / capital-reduction ex-date of a stock that was a Nifty-500 member on that date and has no ledger row gets a
    # loud ::warning:: with its measured opening and closing gap, so a human reads the filing and, if holders received another
    # company's shares, adds the row by hand. Warns only — never adjusts anything.
    try:
        _n5 = sorted(
            (json.load(open(os.path.join(HERE, "indices_history.json"))) or {}).get("Nifty 500") or [],
            key=lambda s: s.get("effectiveDate", ""),
        )
    except Exception as e:
        _n5 = []
        print(f"  (indices_history.json not loaded: {e} — scheme warning skipped)")

    def _cur(s):
        seen = set()
        while s in rename and s not in seen:
            seen.add(s)
            s = rename[s]
        return s

    def _n500_on(sym, ex):
        iso = "%d-%02d-%02d" % (ex // 10000, ex // 100 % 100, ex % 100)
        snaps = [s for s in _n5 if s.get("effectiveDate", "") <= iso]
        return bool(snaps) and _cur(sym) in {_cur(m) for m in snaps[-1].get("symbols") or []}

    today = datetime.date.today()
    warned = 0
    for sym, ex, subj in logged:
        d = datetime.date(ex // 10000, ex // 100 % 100, ex % 100)
        if not 0 <= (today - d).days <= 30:
            continue
        key_sym = _cur(sym)
        if any(k in (sym, key_sym) and abs(od(e) - od(ex)) <= 7 for (k, e) in led):
            continue
        if not _n500_on(sym, ex):
            continue
        cands = {sym, key_sym} | {o for o, n in rename.items() if _cur(n) == key_sym}
        row = None
        used = None
        for k in range(4):
            dd = d + datetime.timedelta(days=k)
            if dd > today:
                break
            rows = B.fetch_day(dd, jar)
            if not rows:
                continue
            row = next((r for r in rows if r[0] in cands), None)
            used = int(dd.strftime("%Y%m%d"))
            break
        gap = (
            "open %+.2f%% / close %+.2f%% vs prev close %.2f on %d"
            % (100 * (row[6] / row[2] - 1), 100 * (row[1] / row[2] - 1), row[2], used)
            if row and row[2] and row[6]
            else "no bhavcopy row yet"
        )
        print(
            "::warning::§170d scheme ex-date on a Nifty-500 stock with NO demerger_adj row: %s %d '%s' — %s. If the "
            "filing gives holders shares of another company it is a spin-off: add the row by hand (DATA_RUNBOOK §170)."
            % (key_sym, ex, subj, gap)
        )
        warned += 1
    if warned:
        print("  %d Nifty-500 scheme ex-date(s) flagged for a human (§170d)" % warned)

    out = sorted(led.values(), key=lambda x: (x[1], x[0]))
    tmp = OUT + ".tmp"
    json.dump(out, open(tmp, "w"), indent=0)
    os.replace(tmp, OUT)
    print("Wrote %s: %d events (%d new)" % (OUT, len(out), added))


if __name__ == "__main__":
    main()
