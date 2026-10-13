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
"""Re-filing guard (DATA_RUNBOOK §152) — runs in refresh-shareholding.yml after the fetch passes, before commit.

Option C (§142k) keeps a re-filing beside the stored original in scripts/shp_revisions.json and the engine
serves whichever is public. A re-filing that repeats the raw numbers of an original whose stored reading was
HEALED from its own document (SW-2 curated-foreign Any-Other block, §142e, §151) must carry the same heal —
otherwise the heal is silently undone from the re-filing date (JSWSTEEL Sep-2016 35.64 -> 20.62, 42 rows on
2026-09-24). Two checks, both exit 1 on failure:
  1. every sidecar row whose (symbol, as-on) has a VALUE-heal ledger entry must not equal that entry's raw `was`;
  2. every SW-2 'foreign-confirmed' audit cell must still be reflected in the store (fii >= stored_fii + block).
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.argv = [sys.argv[0]]
import fetch_shareholding as FS

led = FS.load_cell_fix()
fix = led.get("fix") or {}
revs = FS.load_revs()
hist = json.load(open(os.path.join(ROOT, "scripts", "shp_history.json"), encoding="utf-8"))
audit = json.load(open(FS.AUDIT_JSON, encoding="utf-8")).get("cells") or {}
bad = []
for sym, qs in revs.items():
    if sym.startswith("_"):
        continue
    for key, rc in qs.items():
        ent = fix.get(sym, {}).get(key)
        if not ent or not FS.VALUE_HEAL_MARK.search(str(ent.get("why", ""))):
            continue
        # §224: a re-filing row that equals its OWN document's adjudication ("<as-on>#rev", §164s part 11) is decided by that
        # reading, whatever the store entry's `was` holds — HINDALCO Mar-2022: the store entry withdraws dii 21.5078 from the
        # ORIGINAL (which names no NPS Trust / ICICI Pru Life), the re-filing names both and its #rev entry reads 21.5078.
        rv = fix.get(sym, {}).get(key + "#rev")
        if rv and rv.get("cell") and FS._rev_same(rc, rv["cell"]):
            continue
        was, cell = ent.get("was"), ent.get("cell")
        if was and cell and not FS._same_cell(was, cell) and FS._same_cell(rc, was):
            bad.append(
                f"revision {sym} {key} repeats the raw numbers of a healed original (fii {rc[1]} vs healed {cell[1]})"
            )
n_ok = 0
for key, v in audit.items():
    if v.get("verdict") != "foreign-confirmed":
        continue
    sym, q = key.split("|")
    cur = (hist.get(sym) or {}).get(q)
    if not cur:
        continue
    ent = fix.get(sym, {}).get(q)
    # §158 / §159 re-adjudicated the block's destination from the filer's own 2022-form placement (fii OR public);
    # a later entry keeps the earlier one under `superseded`, so the whole chain is checked
    link, rowfixed, depth = ent, False, 0
    while isinstance(link, dict) and depth < 8:
        w = str(link.get("why", ""))
        if (
            "\u00a7158 row-level DII heal" in w
            or "\u00a7159 row-level FII heal" in w
            or "\u00a7160 page-era row-level heal" in w
            or "\u00a7164" in w
        ):
            rowfixed = True
            break
        link = link.get("superseded")
        depth += 1
    if rowfixed:
        n_ok += 1
        continue
    want = (v.get("stored_fii") or 0.0) + (v.get("oth") or 0.0)
    if cur[1] + 0.03 < want:
        bad.append(
            f"store {sym} {q} lost its foreign Any-Other block: fii {cur[1]}, adjudicated {want:.4f}"
        )
    else:
        n_ok += 1
# §224 (2026-10-07): the re-filing rows proven wrong from the exchange record stay fixed IN THE FILE (build_stock_fin reads
# shp_revisions.json raw, without load_revs): no row whose source is a dropped document, no row still on a re-dated `was`.
raw = json.load(open(FS.REVS, encoding="utf-8")) if os.path.exists(FS.REVS) else {}
rfx = FS.load_rev_fix()
n_led = 0
for k, ent in (rfx.get("drop") or {}).items():
    n_led += 1
    sym, key = k.split("|", 1)
    rc = (raw.get(sym) or {}).get(key)
    if not ent.get("file"):
        bad.append(f"shp_rev_fix drop {k} has no file")
    elif isinstance(rc, list) and len(rc) > 7 and ent["file"] in str(rc[7]):
        bad.append(
            "re-filing {} {} is back although §224 dropped its document {} ({})".format(
                sym, key, ent["file"], ent.get("class")
            )
        )
for k, ent in (rfx.get("redate") or {}).items():
    n_led += 1
    sym, key = k.split("|", 1)
    rc = (raw.get(sym) or {}).get(key)
    if not ent.get("was") or not ent.get("sub") or ent["sub"] >= ent["was"]:
        bad.append(
            "shp_rev_fix redate {} is malformed (was {}, sub {})".format(
                k, ent.get("was"), ent.get("sub")
            )
        )
    elif isinstance(rc, list) and len(rc) > 5 and str(rc[5]) == ent["was"]:
        bad.append(
            "re-filing {} {} is dated {} again although §224 proved {}".format(
                sym, key, ent["was"], ent["sub"]
            )
        )
if bad:
    for b in bad[:40]:
        print("GUARD FAIL:", b)
    print("guard_shp_revisions: %d problem(s)" % len(bad))
    sys.exit(1)
print(
    "guard_shp_revisions OK: %d sidecar rows checked against value heals, %d audited foreign blocks present in the store, "
    "%d §224 date/drop fixes still in the file"
    % (sum(len(q) for s, q in revs.items() if not s.startswith("_")), n_ok, n_led)
)
