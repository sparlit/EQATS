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
"""§88b MTO sweep — BUILD stage. Parses the cached MTO files, resolves era symbols to
merged bin symbols, VALIDATES against the live bin (volume identity + dv overlap), then
extends scripts/dv_fill_hist.json.gz fill-only (existing cells preserved verbatim).

Formats (measured 2026-08-11):
  2002-01-02 .. 2002-02-11 : 20,SYMBOL,SERIES,DELIV_QTY          (4 fields; hdr total == sum(qty)
                             proves qty is the DELIVERABLE quantity; pct = qty / bin volume)
  2002-02-14 .. today      : 20,SR,SYMBOL,SERIES,TRADED,DELIV,PCT (7 fields; hdr total == sum(DELIV))
Conventions preserved from the 2026-08-02 ledger: EQ row preferred then BE then BZ; true 0.00
stored as 0.01 (bin dv==0 stays the 'unavailable' sentinel); fill-only where dv==0.
"""
import gzip
import json
import os
import re
from collections import Counter, defaultdict

SP = os.environ.get("MTO_SP", os.path.expanduser("~/.cache/mto_sweep"))
CACHE = os.path.join(SP, "mto")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERIES = ("EQ", "BE", "BZ")


def load_bin():
    # MTO_BIN env = path of the bin to validate against. The in-repo docs/sf_stock_data.bin is a
    # FROZEN slim snapshot (weekly bars pre-2018, §103) — point this at the live release asset
    # (build_coverage_matrix.js caches it at $TMPDIR/sf_stock_data_live.bin) for any real sweep.
    D = json.loads(
        gzip.decompress(open(os.environ.get("MTO_BIN") or os.path.join(ROOT, "docs", "sf_stock_data.bin"), "rb").read())
    )
    data = D["data"]
    pos = {}  # sym -> {ymd:int -> idx}
    for sym, e in data.items():
        pos[sym] = {d: i for i, d in enumerate(e["d"])}
    return data, pos


def old_to_current():
    m = dict(json.load(open(os.path.join(HERE, "_rename_map.json"))))  # old -> new
    # MANUAL_MERGE in update_sf_data.py is new<-old; regex it out so the two never drift
    src = open(os.path.join(HERE, "update_sf_data.py")).read()
    blk = src[src.index("MANUAL_MERGE = {") :]
    blk = blk[: blk.index("merged = 0")]
    for new, old in re.findall(r'"([A-Z0-9&\-]+)":\s*"([A-Z0-9&\-]+)"', blk):
        m.setdefault(old, new)
    # transitive closure, cycle-guarded
    out = {}
    for old in m:
        cur, seen = old, set()
        while cur in m and cur not in seen:
            seen.add(cur)
            cur = m[cur]
        out[old] = cur
    return out


def rename_chain():
    """old -> [hop1, hop2, ..., terminal]: EVERY key on the rename chain, nearest first.
    The bin keeps history under whichever hop it merged to, not necessarily the terminal —
    TELCO -> TATAMOTORS -> TMPV, and the 2002 bars live under TATAMOTORS. old_to_current()
    (terminal only) sent TELCO's MTO rows to TMPV, found no bar there, and dropped them as
    'unmatched' (WP3 2026-09-02: 79 Nifty-500 member-day cells behind that one gap). Callers
    must try each hop and take the first key with a bar on that date."""
    m = dict(json.load(open(os.path.join(HERE, "_rename_map.json"))))
    src = open(os.path.join(HERE, "update_sf_data.py")).read()
    blk = src[src.index("MANUAL_MERGE = {") :]
    blk = blk[: blk.index("merged = 0")]
    for new, old in re.findall(r'"([A-Z0-9&\-]+)":\s*"([A-Z0-9&\-]+)"', blk):
        m.setdefault(old, new)
    out = {}
    for old in m:
        cur, seen, hops = old, set(), []
        while cur in m and cur not in seen:
            seen.add(cur)
            cur = m[cur]
            hops.append(cur)
        out[old] = hops
    return out


def parse_file(path):
    """-> {sym: {series: (traded|None, deliv, pct|None)}}"""
    rows = {}
    for line in re.split(r"[\r\n]+", open(path, errors="replace").read()):
        if not line.startswith("20,"):
            continue
        p = line.split(",")
        if len(p) == 7:
            sym, ser = p[2].strip(), p[3].strip()
            if ser not in SERIES:
                continue
            try:
                t, q, pct = int(p[4]), int(p[5]), float(p[6])
            except ValueError:
                continue
            rows.setdefault(sym, {})[ser] = (t, q, pct)
        elif len(p) == 4:
            sym, ser = p[1].strip(), p[2].strip()
            if ser not in SERIES:
                continue
            try:
                q = int(p[3])
            except ValueError:
                continue
            rows.setdefault(sym, {})[ser] = (None, q, None)
    return rows


def main():
    data, pos = load_bin()
    chain = rename_chain()
    files = sorted(f for f in os.listdir(CACHE) if f.endswith(".DAT"))
    print("cached MTO files:", len(files), flush=True)

    fills = defaultdict(dict)  # sym -> {ymd_str: value}
    add_year = Counter()  # new cells per year
    vol_ok = vol_bad = 0  # control A: bin v == MTO traded (7-field)
    dv_ok = dv_bad = 0  # control B: bin dv>0 == MTO pct to 0.01
    unmatched = Counter()  # MTO syms with no bin row that date
    ratio_bad = 0
    e2_cells = 0  # 4-field era cells

    volmiss = Counter()
    ambig = Counter()
    v0 = 0
    wrong_stored = Counter()
    wrong_samples = []
    wrong_cells = []
    for fn in files:
        ymd = int(fn[:8])
        ys = fn[:8]
        rows = parse_file(os.path.join(CACHE, fn))
        # group candidate MTO rows per target bin symbol (exact name + rename-mapped names
        # can COLLIDE on one target — DVL: DPL+DTIL both map there; the bin bar's own traded
        # volume is the only honest arbiter of which security the bar belongs to)
        cand = defaultdict(list)  # tgt -> [(sym, series, traded, deliv, pct)]
        for sym, byser in rows.items():
            tgt = None
            if sym in pos and ymd in pos[sym]:
                tgt = sym
            else:  # walk EVERY hop of the rename chain, nearest first (see rename_chain)
                for c in chain.get(sym, ()):
                    if c in pos and ymd in pos[c]:
                        tgt = c
                        break
            if tgt is None:
                unmatched[sym] += 1
                continue
            for ser, (t, q, pct) in byser.items():
                cand[tgt].append((sym, ser, t, q, pct))
        for tgt, rowsc in cand.items():
            e = data[tgt]
            i = pos[tgt][ymd]
            v = e["v"][i]
            if not v:
                v0 += 1
                continue
            sev = {s: k for k, s in enumerate(SERIES)}
            e7 = [r for r in rowsc if r[4] is not None]
            e4 = [r for r in rowsc if r[4] is None]
            pct = None
            if e7:
                exact = sorted((r for r in e7 if r[2] == v), key=lambda r: (sev[r[1]], r[0] != tgt))
                if exact:
                    pct = exact[0][4]
                    vol_ok += 1
                else:
                    vol_bad += 1
                    volmiss[ys[:4]] += 1
            elif e4:  # 2002-01..02-11 era: no traded column; deliv/bin-volume, ambiguity skipped
                fit = [r for r in e4 if r[3] <= v * 1.005]
                if len(fit) == 1:
                    pct = min(100.0, 100.0 * fit[0][3] / v)
                    e2_cells += 1
                elif len(fit) > 1:
                    ambig[ys[:4]] += 1
                else:
                    ratio_bad += 1
            if pct is None:
                continue
            cur = e["dv"][i]
            if cur:
                if abs(cur - pct) <= 0.011:
                    dv_ok += 1
                else:
                    dv_bad += 1
                    wrong_stored[ys[:4]] += 1
                    wrong_cells.append((tgt, ys, cur, round(pct, 2)))
                    if len(wrong_samples) < 12:
                        wrong_samples.append((tgt, ys, cur, pct))
                continue
            val = round(pct, 2)
            if val == 0:
                val = 0.01
            if val == int(val):
                val = int(val)
            fills[tgt][ys] = val
            add_year[ys[:4]] += 1

    print(
        "\ncontrol A (a volume-matched MTO row exists): ok=%d none=%d (%.3f%%)"
        % (vol_ok, vol_bad, 100.0 * vol_ok / max(1, vol_ok + vol_bad)),
        flush=True,
    )
    print("   no-volume-match skips per year:", dict(sorted(volmiss.items())), flush=True)
    print(
        "control B (existing bin dv == volume-matched MTO pct): ok=%d bad=%d (%.4f%% match)"
        % (dv_ok, dv_bad, 100.0 * dv_ok / max(1, dv_ok + dv_bad)),
        flush=True,
    )
    print(
        "   stored-cell-contradicts-volume-matched-row (old ledger wrong-company cells), per year:",
        dict(sorted(wrong_stored.items())),
        flush=True,
    )
    for s in wrong_samples:
        print("   sample:", s)
    print(
        "4-field-era cells: %d (zero-volume bars: %d, ambiguous: %s, no-fit skips: %d)"
        % (e2_cells, v0, dict(ambig) or 0, ratio_bad),
        flush=True,
    )
    print("unmatched MTO symbols (top 15):", unmatched.most_common(15), flush=True)
    print("unmatched total rows:", sum(unmatched.values()), "distinct syms:", len(unmatched), flush=True)
    print("\nnew cells per year:")
    for y in sorted(add_year):
        print(" ", y, add_year[y])
    print("total new cells:", sum(add_year.values()), "across", len(fills), "symbols", flush=True)

    json.dump(dict(fills.items()), open(os.path.join(SP, "new_fills.json"), "w"))
    json.dump(wrong_cells, open(os.path.join(SP, "wrong_cells.json"), "w"))
    print("wrote new_fills.json + wrong_cells.json (merge stage separate — inspect controls first)", flush=True)


if __name__ == "__main__":
    main()
