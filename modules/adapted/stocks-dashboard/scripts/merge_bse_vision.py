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
"""Merge vision-extracted BSE quarterly numbers into docs/bse_fundamentals.json and clear those scrips
from the OCR-fail ledger (so build_bse_results promotes them from 'PDF only' to real numbered rows).

Input: a JSON file (arg1) that is a list of
  {"exch","sym","scrip","ok":bool,"basis":"C|S","qe":"YYYYMMDD",
   "cur":{"rev","op","pat"},"prev":{...},"yago":{...},"note"}
where qe is the quarter the reader was asked for (bse_vision_prep's manifest carries it per company),
prev = the quarter before it and yago = the same quarter a year earlier. Values are ₹ crore.
The pre-2026-09-27 shape keyed "jun2026"/"mar2026"/"jun2025" is still accepted (Jun-2026 season only).

FILL-ONLY: a stored cell is never replaced or re-dated. A read may only add a figure the stored cell
lacks, and only on the same basis (C/S). Until 2026-09-27 this merge overwrote whole cells.

Run: python -X utf8 scripts/merge_bse_vision.py <results.json> [--qefix <outdir>/qe_fix_run.json]
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import qe_util as QU

HERE = os.path.dirname(os.path.abspath(__file__))
FUND = os.path.join(HERE, "..", "docs", "bse_fundamentals.json")
FAILS = os.path.join(HERE, "_bse_fund_fail.json")
DONE = os.path.join(HERE, "_bse_fund_done.json")
VFILLS = os.path.join(
    HERE, "..", "docs", "vision_fills.json"
)  # NSE overlay the page applies to empty cells
QFIX = os.path.join(HERE, "..", "docs", "feed_qe_fix.json")  # "SYM|YYYY-MM-DD" -> real quarter-end


def feed_ann():
    """{(TICKER, quarter-end int): earliest filing date YYYYMMDD int} from the results feed — the day that
    QUARTER was first declared. Keyed by quarter: the ticker's newest row is often another quarter (a late
    March result, a re-submission), which gave every late-filer read ann=0 and could stamp a June read with
    a September re-filing's date (2026-09-27 audit)."""
    try:
        rows = json.load(
            open(os.path.join(HERE, "..", "docs", "results_feed.json"), encoding="utf-8")
        )["rows"]
    except Exception:
        return {}
    out = {}
    for r in rows:
        try:
            d = int(r[2][:10].replace("-", ""))
            q = int(r[3] or 0)
        except (ValueError, TypeError, IndexError):
            continue
        if not q:
            continue
        k = (str(r[0]).upper(), q)
        if k not in out or d < out[k]:
            out[k] = d
    return out


LEGACY = [
    ("jun2026", 20260630),
    ("mar2026", 20260331),
    ("jun2025", 20250630),
]  # old reader output keys


def quarters_of(it):
    """[(qe_str, figures), ...] for one read, current quarter FIRST. [] when the read names no quarter."""
    try:
        q = int(str(it.get("qe") or "0"))
    except ValueError:
        q = 0
    if QU.is_qe(q):
        return [
            (str(q), it.get("cur") or {}),
            (str(QU.prevq(q)), it.get("prev") or {}),
            (str(QU.yago(q)), it.get("yago") or {}),
        ]
    if any(k in it for k, _ in LEGACY):
        return [(str(qe), it.get(k) or {}) for k, qe in LEGACY]
    return []


def fill(cells, qe, rec, basis, ann=0, src="vision"):
    """Fill-only merge of one quarter's figures into cells[qe]. Returns True if anything was added."""
    new = {k: _num(rec.get(k)) for k in ("rev", "op", "pat") if rec.get(k) is not None}
    if not new:
        return False
    old = cells.get(qe)
    if old is None:
        d = {"pat": new.get("pat"), "ann": ann or 0, "basis": basis, "src": src}
        d.update({k: v for k, v in new.items() if k != "pat"})
        cells[qe] = d
        return True
    if old.get("basis", basis) != basis:
        return False  # never mix C and S figures in one cell
    added = False
    for k, v in new.items():
        if old.get(k) is None:
            old[k] = v
            added = True
    if added and not old.get("ann") and ann:
        old["ann"] = ann
    return added


def reapply_qefix(path):
    """Re-apply the quarter fixes bse_vision_prep resolved EARLIER IN THIS RUN (it journals them to
    <outdir>/qe_fix_run.json, outside the repo).

    Why this exists: prep writes docs/feed_qe_fix.json itself, but the routine re-syncs with
    `git reset --hard origin/main` between prep and merge — the laptop can sleep for hours mid-run — and
    that discards prep's working-tree write. Re-running prep can't bring it back either: the names it
    resolved are no longer pending, so they're never re-scanned, and a mislabelled quarter sits phantom-
    pending until someone notices by hand (2026-07-27: HMT and SGLRES). Idempotent — safe to re-run.
    """
    try:
        run = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        print(f"  ⚠ qefix: {path} unreadable ({e}) — this run's quarter fixes were NOT re-applied")
        return
    if not run:
        print("  qefix: no quarter fixes resolved this run")
        return
    try:
        cur = json.load(open(QFIX, encoding="utf-8"))
    except Exception:
        cur = {}
    add = {k: v for k, v in run.items() if cur.get(k) != v}
    if not add:
        print("  qefix: all %d already in feed_qe_fix.json" % len(run))
        return
    cur.update(add)
    json.dump(cur, open(QFIX, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(
        "  qefix: re-applied %d of %d into feed_qe_fix.json (%d total) — %s"
        % (
            len(add),
            len(run),
            len(cur),
            ", ".join("{}={}".format(*kv) for kv in sorted(add.items())),
        )
    )


def _num(v):
    """A reader's figure -> float rounded to 2 dp, or None. Tolerates '1,234.50' and '(2.10)' (a bracket =
    negative); anything else unreadable is None for THAT figure only — one bad value used to raise and abort
    the whole merge, losing every good read in the batch."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v).strip().replace(",", "").replace("₹", "")
    neg = s.startswith("(") and s.endswith(")")
    try:
        x = float(s.strip("()"))
    except ValueError:
        print(f"  ⚠ unreadable figure {v!r} — skipped")
        return None
    return round(-x if neg else x, 2)


def main():
    argv = sys.argv[1:]
    if "--qefix" in argv:  # do this FIRST: it's independent of the merge below
        i = argv.index("--qefix")
        reapply_qefix(argv[i + 1])
        del argv[i : i + 2]
    items = json.load(open(argv[0], encoding="utf-8"))
    data = json.load(open(FUND, encoding="utf-8"))
    px = data["px"]
    fails = json.load(open(FAILS)) if os.path.exists(FAILS) else {}
    done = set(json.load(open(DONE))) if os.path.exists(DONE) else set()
    vfills = json.load(open(VFILLS, encoding="utf-8")) if os.path.exists(VFILLS) else {}
    fann = feed_ann()
    nb = nn = 0
    for it in items:
        if not it.get("ok"):
            continue
        basis = it.get("basis", "S") or "S"
        sym = (it.get("ticker") or it.get("sym") or "").upper()
        qs = quarters_of(it)
        if not qs:
            print("  ? %-11s read names no quarter (no qe / legacy keys) — skipped" % sym)
            continue
        cq, cur = qs[0]
        if cur.get("pat") is None and cur.get("rev") is None:
            continue
        # NSE entries (exch=="NSE", or no BSE scrip) → overlay file the page applies only to EMPTY cells,
        # so real XBRL always supersedes this vision estimate once it lands. BSE-only → bse_fundamentals.
        if str(it.get("exch", "")).upper() == "NSE" or not str(it.get("scrip") or "").strip():
            e = vfills.setdefault(sym, {})
            added = 0
            for qe, q in qs:
                if fill(e, qe, q, basis):  # overlay cells carry no date and no nulls
                    added += 1
                    e[qe] = {k: v for k, v in e[qe].items() if k != "ann" and v is not None}
            if not e:
                vfills.pop(sym, None)
            nn += 1
            print(
                "  ✓ NSE %-11s %s rev=%s pat=%s op=%s (overlay, %d quarter(s) filled)"
                % (sym, cq, cur.get("rev"), cur.get("pat"), cur.get("op"), added)
            )
        else:
            scrip = str(it["scrip"])
            # real filing date → reaction computes; only when the feed's newest filing IS this quarter's
            ann = fann.get(
                (sym, int(cq)), 0
            )  # the day THIS quarter was declared (0 = not in the feed window)
            cells = px.setdefault(scrip, {})
            added = sum(fill(cells, qe, q, basis, ann=(ann if qe == cq else 0)) for qe, q in qs)
            if not cells:
                px.pop(scrip, None)
            if added:  # a rejected read (other basis / nothing new) must not
                fails.pop(scrip, None)
                done.add(scrip)  # clear the fail count or mark the scrip handled
            nb += 1
            print(
                "  ✓ BSE %-11s (%s) %s rev=%s pat=%s op=%s (%d quarter(s) filled)"
                % (sym, scrip, cq, cur.get("rev"), cur.get("pat"), cur.get("op"), added)
            )
    json.dump(data, open(FUND, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(fails, open(FAILS, "w"))
    json.dump(sorted(done), open(DONE, "w"))
    json.dump(
        vfills, open(VFILLS, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":")
    )
    print("Merged %d BSE-only into bse_fundamentals.json, %d NSE into vision_fills.json" % (nb, nn))


if __name__ == "__main__":
    main()
