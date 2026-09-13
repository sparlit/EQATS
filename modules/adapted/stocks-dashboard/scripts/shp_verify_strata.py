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
"""FREEZE the Phase-3 stratified sample for the SHP verify campaign.

Deterministic by construction: within each stratum, members are ordered by md5(symbol) and the
lowest N are taken. Any agent, on any machine, re-derives the identical list — so the sample can
never be quietly reshaped to flatter numbers, and a re-run after a heal compares like with like.

Strata (SHP_VERIFY_CAMPAIGN §5): cap terciles of the CURRENT Nifty 500 that we actually hold
history for, plus the awkward cases each trap needs — renames (T9), the wayback-sourced era (T3),
the BSE-ledger era, this week's blackout heals, banks/insurers/NBFCs (bucket definitions differ
most there), ADR/GDR names (T1), fresh IPOs (first-filing edge), and index exits still in history.

  python3 -X utf8 scripts/shp_verify_strata.py --pin 93de247c --out strata.json
"""
import argparse
import collections
import gzip
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# hand-picked members that exist to exercise a NAMED trap, not to be representative
BLACKOUT = ["MCX", "ABBOTINDIA", "BAYERCROP", "NESTLEIND", "WESTLIFE", "ITC"]  # 2026-08-09 sweep heals
ADR_GDR = ["INFY", "WIPRO", "ICICIBANK", "HDFCBANK"]  # T1 look-through
DEFN_HARD = ["SBIN", "KOTAKBANK", "AXISBANK", "LICI", "SBILIFE", "BAJFINANCE", "CHOLAFIN"]
TRUST_PROM = ["M&M", "ETERNAL", "HEROMOTOCO"]  # T2 / no-promoter


def git_show(path, pin, binary=False):
    r = subprocess.run(["git", "show", f"{pin}:{path}"], capture_output=True, cwd=REPO)
    if r.returncode:
        return None
    return r.stdout


def h(sym):
    return hashlib.md5(sym.encode()).hexdigest()


def take(pool, n, used):
    """Lowest md5 first, skipping anything already drawn into an earlier stratum."""
    out = []
    for s in sorted(set(pool), key=h):
        if s in used:
            continue
        out.append(s)
        used.add(s)
        if len(out) >= n:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", default="origin/main")
    ap.add_argument("--out", default="strata.json")
    a = ap.parse_args()

    HIST = json.loads(git_show("scripts/shp_history.json", a.pin))
    held = {s: len(HIST[s]) for s in HIST if not s.startswith("_")}

    # dash_slim.meta is keyed "<SYM>.NS" -> {symbol, name, sector, industry, mcap, …}
    slim = json.loads(gzip.decompress(git_show("docs/dash_slim.bin", a.pin)))
    mcap, sector = {}, {}
    for r in slim.get("meta", {}).values():
        sym, mc = r.get("symbol"), r.get("mcap")
        if sym and mc:
            mcap[sym] = float(mc)
            sector[sym] = r.get("sector") or ""

    # indices_history is a LIST of {effectiveDate, symbols} snapshots — newest effective date wins
    IH = json.loads(git_show("scripts/indices_history.json", a.pin))
    snaps = IH.get("Nifty 500") or IH.get("NIFTY 500") or []
    snaps = sorted(snaps, key=lambda s: s.get("effectiveDate", ""))
    latest_snap = snaps[-1]["effectiveDate"] if snaps else None
    members = set(snaps[-1]["symbols"]) if snaps else set()
    universe = [s for s in members if s in held and s in mcap]
    universe.sort(key=lambda s: -mcap[s])
    third = max(1, len(universe) // 3)
    mega, mid, small = universe[:third], universe[third : 2 * third], universe[2 * third :]

    RMAP = json.loads(git_show("scripts/_rename_map.json", a.pin) or b"{}")
    renamed = [s for s in (RMAP.values() if isinstance(RMAP, dict) else []) if held.get(s, 0) >= 8]
    if not renamed:
        renamed = [s for s in (RMAP.keys() if isinstance(RMAP, dict) else []) if held.get(s, 0) >= 8]

    def ledger_syms(path, min_cells):
        raw = git_show(path, a.pin)
        if raw is None:
            return []
        doc = json.loads(gzip.decompress(raw))
        fills = doc.get("fills", doc)
        return [s for s, q in fills.items() if isinstance(q, dict) and len(q) >= min_cells]

    wayback = ledger_syms("scripts/shp_fill_hist_2010_2016.json.gz", 12)
    bse1619 = ledger_syms("scripts/shp_fill_hist_2016_2019.json.gz", 8)
    ipos = [s for s in held if held[s] <= 4 and s in members]
    exits = [s for s in held if s not in members and held[s] >= 12]

    used, strata = set(), collections.OrderedDict()
    for name, pool, n in [
        ("blackout_heals", BLACKOUT, 6),
        ("adr_gdr", ADR_GDR, 3),
        ("definition_hard", DEFN_HARD, 5),
        ("trust_or_noprom", TRUST_PROM, 3),
        ("renamed", renamed, 5),
        ("wayback_era", wayback, 5),
        ("bse_1619_era", bse1619, 5),
        ("cap_mega", mega, 10),
        ("cap_mid", mid, 10),
        ("cap_small", small, 10),
        ("recent_ipo", ipos, 2),
        ("index_exit", exits, 2),
    ]:
        picked = take([s for s in pool if s in held], n, used)
        strata[name] = picked
        if len(picked) < n:
            print("  ! stratum %s: only %d/%d available" % (name, len(picked), n), file=sys.stderr)

    allsyms = sorted(used)
    doc = {
        "_meta": {
            "pin": a.pin,
            "rule": "lowest md5(symbol) within each stratum, earlier strata win",
            "universe": len(universe),
            "n500_snapshot": latest_snap,
            "total": len(allsyms),
        },
        "strata": strata,
        "symbols": allsyms,
        "quarters_held": {s: held[s] for s in allsyms},
    }
    json.dump(doc, open(a.out, "w", encoding="utf-8"), indent=1)

    print("universe (current N500 with mcap and history): %d   snapshot %s" % (len(universe), latest_snap))
    for k, v in strata.items():
        print("  %-16s %2d  %s" % (k, len(v), ",".join(v)))
    print("TOTAL %d symbols, %d stock-quarters to diff" % (len(allsyms), sum(held[s] for s in allsyms)))
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
