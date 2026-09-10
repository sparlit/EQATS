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
"""Heal the `mf` slot of SHP cells the pre-2026-08-07 parser wrote as 0.0 (runbook §22g).

THE BUG (fixed in parse_shp by commit 34398450, this script repairs its residue): new-format
filings spell the mutual-fund member BOTH ways — `MutualFundsOrUTIMember` and the old format's
`MutualFundsOrUtiMember` (lowercase ti). MEMBERS mapped only the uppercase one, so every filing
carrying the lowercase spelling (all BSE copies, and every NSE filing before ~Jul-2025) stored
mf = 0.0, which the stock page reads as "no mutual-fund holding" instead of "not found".
fii/dii/prom/ins were never affected — they come from their own facts.

Scope is measured, not assumed. The hole is in the new-format branch, but the format boundary is
NOT the quarter: a filing uses the taxonomy that was current when it was SUBMITTED, so late and
revised filings of old quarters come back new-format too (MANPASAND Mar-2022, submitted Nov-2024:
InstitutionsDomesticMember 5.38 with the MF row spelled lowercase — stored mf 0.0, real 5.38).
So the sweep runs over the whole XBRL era, from BSE's first real file (Jun-2016), and lets the
re-parse decide. Two cuts are safe and keep it to ~25k fetches:
  * mf must be 0 AND dii > 0 — MF ⊆ DII, so mf=0 with dii=0 is provably correct (7.9k cells).
  * quarters before 2016-06-30 are out of reach, not skipped: those cells come from Wayback-archived
    Moneycontrol pages (§22b) and no XBRL exists for them anywhere (427 candidates).

ROUTES (both give the same numbers; NSE is preferred because it is the source the stored cell
came from). The NSE master API serves the filing SEASON of any quarter back to Sep-2022 —
~1,900 rows for 2022-09-30, contra the runbook's old "recent rolling window only" note, which
was an artifact of the as-on → submission-date window flip. Older quarters do collapse to a
trickle (62 rows for Mar-2021), which is exactly why the BSE fallback exists.

WRITES A LEDGER, never shp_history directly (§22 one-writer rule):
scripts/shp_mf_heal.json.gz
  {"heals":  {SYM: {QE: [mf, prom, fii, dii, "src", "sub"]}},   <- patch, with the reference cell
   "zeros":  {SYM: [QE, ...]},                                  <- re-parsed, MF really is 0
   "rejects":{SYM: {QE: "reason"}}}                             <- parse/guard refused; never patched
applied by fetch_shareholding.apply_mf_heal_ledger(), which touches cell[3] ONLY, only when the
stored cell still reads 0.0 and still matches the prom/fii/dii it was measured against.

  python3 -X utf8 scripts/heal_shp_mf.py                  # every candidate, newest quarter first
  python3 -X utf8 scripts/heal_shp_mf.py --sample 60      # smoke test, spread over eras + routes
  python3 -X utf8 scripts/heal_shp_mf.py --from-qe 2022-09-30   # narrow to the new-format era
Resumable: re-running skips every (sym,qe) already in heals/zeros/rejects.
"""
import argparse
import collections
import gzip
import json
import os
import random
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import build_fundamentals as B  # NSE session
import fetch_shareholding as FS  # parse_shp — the SAME parser the live pipeline uses
import fetch_shp_bse_hist as BH  # BSE transport + scripcode resolution

LEDGER = os.path.join(HERE, "shp_mf_heal.json.gz")
CACHE = os.path.join(HERE, "_shp_mf_cache")  # per-quarter NSE master lists (gitignored)

FIRST_QE = "2016-06-30"  # BSE's earliest real XBRL — before it there is no file to re-read
THREADS = 6  # nsearchives is a static host; the live fetcher uses 6
FLUSH_EVERY = 200
TOL = 0.5  # pp — the re-parsed cell must be the SAME filing we stored


# ---------------------------------------------------------------- ledger
def load_ledger():
    if os.path.exists(LEDGER):
        with gzip.open(LEDGER, "rt", encoding="utf-8") as fh:
            d = json.load(fh)
    else:
        d = {}
    d.setdefault("heals", {})
    d.setdefault("zeros", {})
    d.setdefault("rejects", {})
    return d


def save_ledger(led):
    led["_meta"] = {
        "source": "NSE corporate-share-holdings-master XBRL + BSE SHPQNewFormat fallback",
        "built": time.strftime("%Y-%m-%d %H:%M IST"),
        "what": "mf-slot heal for cells written before the MutualFundsOrUtiMember fix (runbook §22g)",
        "healed": sum(len(v) for v in led["heals"].values()),
        "confirmed_zero": sum(len(v) for v in led["zeros"].values()),
        "rejected": sum(len(v) for v in led["rejects"].values()),
    }
    tmp = LEDGER + ".tmp%d" % os.getpid()
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(led, fh, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, LEDGER)


# ---------------------------------------------------------------- NSE master cache
def master_rows(jar, qe):
    """{SYM: (xbrl_url, sub_date)} for a quarter — newest submission per symbol. Cached on disk:
    the master is ~4,800 rows and the same list serves every candidate in that quarter."""
    os.makedirs(CACHE, exist_ok=True)
    cf = os.path.join(CACHE, f"master_{qe}.json")
    if os.path.exists(cf) and os.path.getsize(cf) > 200:
        try:
            return json.load(open(cf, encoding="utf-8"))
        except Exception:
            pass
    best = {}
    for r in FS.fetch_master(jar, qe):
        sym = str(r.get("symbol") or "").strip().upper()
        sub = FS.iso_date(r.get("submissionDate")) or FS.iso_date(r.get("broadcastDate"))
        xb = str(r.get("xbrl") or "").strip()
        if not sym or not sub or not xb.lower().startswith("http"):
            continue
        if sym not in best or sub >= best[sym][1]:
            best[sym] = [xb, sub]
    json.dump(best, open(cf, "w", encoding="utf-8"), separators=(",", ":"))
    return best


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-qe", default=FIRST_QE)
    ap.add_argument("--limit", type=int, default=0, help="stop after N candidates, newest first")
    ap.add_argument("--sample", type=int, default=0, help="N candidates spread over every era/route (smoke test)")
    ap.add_argument("--threads", type=int, default=THREADS)
    ap.add_argument("--bse-only", action="store_true", help="skip the NSE route (transport debugging)")
    a = ap.parse_args()

    hist = FS.load_hist()
    FS.apply_bse_hist_ledger(hist)  # heal what the merged history will actually look like
    names = hist.get("_names", {})
    led = load_ledger()
    heals, zeros, rejects = led["heals"], led["zeros"], led["rejects"]
    done = {(s, q) for s, qs in heals.items() for q in qs}
    done |= {(s, q) for s, qs in zeros.items() for q in qs}
    done |= {(s, q) for s, qs in rejects.items() for q in qs}

    todo, skip_dii0 = [], 0
    for sym, qs in hist.items():
        if sym.startswith("_") or not isinstance(qs, dict):
            continue
        for qe, c in qs.items():
            if qe < a.from_qe or len(c) < 6 or c[3]:
                continue
            if not c[2] or c[2] <= 0:  # MF ⊆ DII — a zero DII proves the zero MF
                skip_dii0 += 1
                continue
            if (sym, qe) in done:
                continue
            todo.append((sym, qe, c))
    todo.sort(key=lambda t: (t[1], t[0]), reverse=True)  # newest quarter first
    print(
        "candidates: %d cells over %d quarters (%s ..), %d skipped as dii=0 (provably correct), "
        "%d already in the ledger"
        % (len(todo), len({t[1] for t in todo}), min([t[1] for t in todo], default="-"), skip_dii0, len(done))
    )
    if a.sample:
        random.Random(20260807).shuffle(todo)
        todo = todo[: a.sample]
        todo.sort(key=lambda t: (t[1], t[0]), reverse=True)
    elif a.limit:
        todo = todo[: a.limit]

    # --- NSE masters for the quarters we need (1 call each, cached)
    masters = {}
    if not a.bse_only:
        jar = B.nse_jar()
        for qe in sorted({t[1] for t in todo}, reverse=True):
            try:
                masters[qe] = master_rows(jar, qe)
            except Exception as e:
                print(f"  master {qe} failed ({e!r}) — those cells go to BSE")
                masters[qe] = {}
    else:
        jar = None
    cmap = by_name = None  # BSE scripcode maps (one 10k-row fetch, disk-cached)

    n_nse = sum(1 for s, q, c in todo if s in masters.get(q, {}))
    print("route: %d via NSE, %d via BSE fallback" % (n_nse, len(todo) - n_nse))
    if todo:
        # Always built, not just when a cell has no NSE row: an NSE row can point at a file that
        # 404s (nsearchives drops old XBRLs — BFUTILITIE 2016-17, RAJESHEXPO Mar-2026), and BSE's
        # copy of the same filing is right there.
        cmap, by_name = BH.build_codemap(names)

    lock = threading.Lock()
    cnt = collections.Counter()

    def work(item):
        sym, qe, cell = item
        src = None
        try:
            hit = masters.get(qe, {}).get(sym)
            if hit and not a.bse_only:
                try:
                    root = ET.fromstring(FS.fetch_xbrl(hit[0], jar))
                    src = f"nse:{hit[1]}"
                except Exception:
                    hit = None  # dead NSE file — fall through to BSE
            if not hit or a.bse_only:
                code = BH.resolve(sym, cmap, by_name, names) if cmap else None
                if code is None:
                    return sym, qe, cell, ("REJECT", "no NSE filing and no BSE scripcode")
                r = BH.row_for(BH.quarter_list(code), qe)
                if r is None:
                    return sym, qe, cell, ("REJECT", "no filing at NSE or BSE")
                root = ET.fromstring(BH.get(BH.xbrl_url(r)))
                src = "bse:%d:%s" % (code, r.get("qtrid"))
        except Exception as e:
            return sym, qe, cell, ("ERR", repr(e)[:110])
        res = FS.parse_shp(root, qe)
        if not isinstance(res, dict):
            return sym, qe, cell, ("REJECT", "parse refused (no anchor / unknown vintage)")
        # The re-parse must be the SAME filing we stored, or its mf does not belong in that cell.
        for i, k in ((0, "prom"), (1, "fii"), (2, "dii")):
            if abs((cell[i] or 0.0) - res[k]) > TOL:
                return (
                    sym,
                    qe,
                    cell,
                    ("REJECT", f"cell mismatch {k} stored {cell[i] or 0.0:.2f} vs {res[k]:.2f} ({src})"),
                )
        if res["mf"] > (cell[2] or 0.0) + 0.05:
            return sym, qe, cell, ("REJECT", "mf {:.2f} > dii {:.2f} ({})".format(res["mf"], cell[2], src))
        return sym, qe, cell, (res["mf"], src)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.threads) as ex:
        for fut in as_completed([ex.submit(work, it) for it in todo]):
            sym, qe, cell, out = fut.result()
            with lock:
                if isinstance(out, tuple) and out[0] in ("REJECT", "ERR"):
                    cnt[out[0]] += 1
                    if out[0] == "REJECT":
                        rejects.setdefault(sym, {})[qe] = out[1]
                    if cnt[out[0]] <= 12:
                        print(f"  {out[0]} {sym} {qe}: {out[1]}")
                elif out[0] > 0:
                    heals.setdefault(sym, {})[qe] = [out[0], cell[0], cell[1], cell[2], out[1], str(cell[5])]
                    cnt["heal"] += 1
                else:
                    zeros.setdefault(sym, []).append(qe)
                    cnt["zero"] += 1
                n = cnt["heal"] + cnt["zero"]
                if n and n % FLUSH_EVERY == 0:
                    save_ledger(led)
                    print(
                        "  ... %d/%d done — %d healed, %d really zero (%.0fs)"
                        % (n, len(todo), cnt["heal"], cnt["zero"], time.time() - t0)
                    )
    for s in zeros:
        zeros[s] = sorted(set(zeros[s]))
    save_ledger(led)
    print(
        "\nDONE in %.1f min: %d healed, %d confirmed genuinely zero, %d rejected, %d transport errors"
        % ((time.time() - t0) / 60.0, cnt["heal"], cnt["zero"], cnt["REJECT"], cnt["ERR"])
    )
    print(
        "ledger: %s — %d heals over %d symbols"
        % (os.path.basename(LEDGER), sum(len(v) for v in heals.values()), len(heals))
    )
    if cnt["heal"]:
        big = sorted(((v[0], s, q) for s, qs in heals.items() for q, v in qs.items()), reverse=True)[:8]
        print("largest heals: " + ", ".join(f"{s} {q} {m:.2f}%" for m, s, q in big))


if __name__ == "__main__":
    main()
