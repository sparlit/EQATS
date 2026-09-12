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
"""Power-of-ten scale errors in the SOURCE XBRL (DATA_RUNBOOK §11).

Some filers' XBRL carries every monetary tag at 10^k times its true value. Our parsers divide
raw rupees by 1e7 and are CORRECT — the file itself is wrong, so a re-parse reproduces the
garbage byte for byte (verified: today's build_revop reproduces 263/263 cached flagged cells,
zero stale artifacts). The proof case is BATAINDIA 20190630, which filed standalone and
consolidated two minutes apart on 2019-08-02:

    std  INDAS_46645_..._02082019101118  FinanceCosts = 313510000000  decimals="-9"
    con  INDAS_46647_..._02082019101327  FinanceCosts =    313510000  decimals="-6"

— the same real number, one of them x1000, and rev/OI/PBET/PAT track it (999.3/1003.6/998.3/
997.6). `decimals` cannot be used to detect this: digits-|decimals| == 4 in the broken filing
AND the good ones, because the filer derives it from the broken value.

Two consumers, one ledger (scale_fix.json):
  * PARSE time — build_revop.py and build_fundamentals.py call factor(filename) and divide, so
    a full rebuild off _xbrl_cache stays clean.
  * ONE-OFF — `python -X utf8 scale_fix.py --apply` repairs the already-built JSONs in place,
    guarded on the recorded pre-fix values so it can never double-divide.

Adding an entry requires a real anchor — see the ledger's _README. Surface candidates with
detect_scale_errors.py, then adjudicate BY HAND: the disease is not auto-detectable, and a
false positive deletes real data (the ORFO lesson, §11).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(HERE, "scale_fix.json")

# sf_revop row: [revStd, revCon, opStd, opCon, patStd, patCon, fin, ebitStd, ebitCon]
SLOTS = {"std": {"rev": 0, "op": 2, "pat": 4, "ebit": 7}, "con": {"rev": 1, "op": 3, "pat": 5, "ebit": 8}}
# fundamentals row: [qe, npStd, annStd, npCon, annCon]
NPIDX = {"std": 1, "con": 3}


def load():
    try:
        return json.load(open(LEDGER, encoding="utf-8")).get("fixes", [])
    except Exception:
        return []


_BY_FILE = None


def factor(fname):
    """10**k for a cache filing known to be scaled, else None. Keyed on the FILENAME because the
    unit of corruption is the FILING — that makes this idempotent (the raw file never changes)
    and identical for every parser that reads it."""
    global _BY_FILE
    if _BY_FILE is None:
        _BY_FILE = {e["file"]: 10.0 ** e["k"] for e in load() if e.get("file")}
    return _BY_FILE.get(os.path.basename(fname))


_BY_CELL = None


def factor_cell(sym, qe, basis):
    """10**k for a (symbol, quarter, basis) known to be scaled, else None.

    The file-keyed `factor()` above is the right hook for anything that reads the XBRL. Some
    writers never see a filename: `apply_owners_full.py` rewrites npCon out of
    `_reattr_owners.json`, which was built from the same poisoned XBRL and therefore carries the
    SCALED owners figure. It runs nightly, AFTER `scale_fix.py --apply`, and silently restored the
    error on 6 cells -- METROBRAND, NAVNETEDUL, PARKHOTELS, JUBLPHARMA, NDTV, PAYTM (found
    2026-08-09; NDTV's npCon sat at -467.5 against a true -46.75). Those are exactly the filings
    that carry a distinct ProfitOrLossAttributableToOwnersOfParent tag, so no file-keyed hook
    could ever have reached them.
    """
    global _BY_CELL
    if _BY_CELL is None:
        _BY_CELL = {(e["sym"].upper(), str(e["qe"]), e["basis"]): 10.0 ** e["k"] for e in load()}
    return _BY_CELL.get((str(sym).upper(), str(qe), basis))


def _close(a, b):
    return a is not None and b is not None and abs(a - b) <= max(0.02, abs(b) * 0.005)


def _fix_revop(path, fixes):
    if not os.path.exists(path):
        return 0, "missing"
    data = json.load(open(path, encoding="utf-8"))
    n = 0
    for e in fixes:
        row = data.get(e["sym"], {}).get(e["qe"])
        if not row:
            continue
        if len(row) < 9:
            row += [None] * (9 - len(row))
        for name, slot in SLOTS[e["basis"]].items():
            want = e["was_revop"].get(name)
            if want is None:
                continue
            if _close(row[slot], want):  # still the scaled value -> repair
                row[slot] = round(want / 10.0 ** e["k"], 2)
                n += 1
        data[e["sym"]][e["qe"]] = row
    json.dump(data, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    return n, "ok"


def _fix_fund(path, fixes):
    """Repair net profit in (sf_)fundamentals.

    Scans BOTH np slots, not just the ledger entry's basis: build_fundamentals can emit a
    standalone AND a consolidated figure from a SINGLE filing, so one scaled file poisons both
    (IRCTC 20220930 and TTML 20190930 each carry the scaled number in npCon as well, even though
    only a standalone filing exists). A slot is only touched when it still holds a value we have
    RECORDED as scaled — so GAEL's npStd 14.55, which a different source got right, is left alone.
    """
    if not os.path.exists(path):
        return 0, "missing"
    data = json.load(open(path, encoding="utf-8"))
    n = 0
    for e in fixes:
        scaled = [v for v in (e.get("was_fund"), e.get("was_revop", {}).get("pat")) if v is not None]
        if not scaled:
            continue
        for row in data.get(e["sym"], []):
            if str(row[0]) != e["qe"]:
                continue
            for i in NPIDX.values():
                for was in scaled:
                    if _close(row[i], was):
                        row[i] = round(was / 10.0 ** e["k"], 2)
                        n += 1
                        break
    json.dump(data, open(path, "w", encoding="utf-8"), separators=(",", ":"))
    return n, "ok"


def apply_live():
    fixes = load()
    if not fixes:
        print("no ledger entries")
        return
    targets = [
        (os.path.join(ROOT, "docs", "sf_revop.json"), _fix_revop),
        (os.path.join(HERE, "revop_fundamentals.json"), _fix_revop),
        (os.path.join(ROOT, "docs", "sf_fundamentals.json"), _fix_fund),
        (os.path.join(HERE, "fundamentals.json"), _fix_fund),
    ]
    for path, fn in targets:
        n, status = fn(path, fixes)
        print("  %-46s %s, %d cell(s) repaired" % (os.path.basename(path), status, n))
    print("(0 repaired = already applied; the was_* guard makes this idempotent)")


if __name__ == "__main__":
    import sys

    if "--apply" in sys.argv:
        print("applying %d ledger fixes to the built JSONs:" % len(load()))
        apply_live()
    else:
        for e in load():
            print("%-11s %s %-3s 1e%-2d %s" % (e["sym"], e["qe"], e["basis"], e["k"], e["file"]))
        print("\n%d filings in the ledger. Use --apply to repair the built JSONs." % len(load()))
