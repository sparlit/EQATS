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
"""Apply INSURER_INBOX entries (typed on docs/insurer-inbox.html, stored in Supabase)
into the fundamentals data — the manual-fill half of the insurer pipeline.

Flow (stdlib-only, safe to run every hour — one HTTP call when the inbox is idle):
  1. Pull kv 'INSURER_INBOX' (newest-first array of {sym,qe,con,ann,force?,ts,...}).
  2. For each entry not yet marked applied/rejected: validate hard (symbol must be
     a known insurer, quarter-end sane, PAT inside a generous multiple of the
     insurer's plausible range — the same gates fetch_insurers.py trusts), then
     fill into docs/sf_fundamentals.json AND scripts/fundamentals.json.
     FILL-ONLY unless the entry carries force=true (an explicit correction).
  3. Touch docs/.fund_updated when anything changed (downstream rebuild steps key
     off it) and write the statuses back to the inbox so the page shows ✅/✖.

Row layout + fill-only semantics mirror fetch_insurers.py set_cell():
  fund[sym] = [[qe, std, annStd, con, annCon], ...]   (qe = YYYYMMDD int, ₹ cr)
Keep INSURERS in sync with scripts/fetch_insurers.py (kept inline here so this
script needs NO pip installs on CI — fetch_insurers imports pymupdf).
"""
import json
import os
import sys
import urllib.request
from datetime import UTC, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS_FUND = os.path.join(HERE, "..", "docs", "sf_fundamentals.json")
SRC_FUND = os.path.join(HERE, "fundamentals.json")
FLAG = os.path.join(HERE, "..", "docs", ".fund_updated")

API = "https://nebjnsndgrhumnkuipqy.supabase.co/rest/v1/rpc/"
ANON = "sb_publishable_MDlQwiVc5deii91__UNeDg_z9r4Fk98"
WRITE = "sw_owner_8Kq2Lm9Xp4Rt7v"

# sym -> (plausible quarterly PAT range Rs cr, has-subsidiaries flag) — mirror of fetch_insurers.INSURERS
INSURERS = {
    "LICI": ((200, 25000), True),
    "SBILIFE": ((30, 2000), False),
    "HDFCLIFE": ((80, 900), True),
    "ICICIPRULI": ((80, 1200), True),
    "ICICIGI": ((30, 1800), False),
    "GICRE": ((10, 4500), True),
    "NIACL": ((-200, 2500), True),
    "STARHEALTH": ((5, 900), False),
    "GODIGIT": ((10, 400), False),
    "NIVABUPA": ((-200, 500), False),
    "MFSL": ((-150, 500), True),
}
VALID_QM = {3: 31, 6: 30, 9: 30, 12: 31}


def rpc(fn, args):
    req = urllib.request.Request(
        API + fn,
        data=json.dumps(args).encode(),
        headers={"apikey": ANON, "Authorization": "Bearer " + ANON, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
    return json.loads(body) if body else None


def ist_today():
    return (datetime.now(UTC) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")


def set_cell(fund, sym, qe, con, con_ann, std=None, std_ann=None, force=False):
    """fetch_insurers.set_cell + an explicit force mode for corrections."""
    rows = fund.setdefault(sym, [])
    row = next((r for r in rows if r[0] == qe), None)
    if row is None:
        row = [qe, None, None, None, None]
        rows.append(row)
        rows.sort(key=lambda r: r[0])
    changed = False
    if con is not None and (row[3] is None or force):
        row[3] = round(con, 2)
        row[4] = con_ann
        changed = True
    if std is not None and (row[1] is None or force):
        row[1] = round(std, 2)
        row[2] = std_ann or con_ann
        changed = True
    return changed


def validate(e):
    """Return an error string, or None when the entry is good to file."""
    sym = e.get("sym")
    qe = e.get("qe")
    con = e.get("con")
    ann = str(e.get("ann") or "")
    if sym not in INSURERS:
        return "unknown insurer symbol"
    if (
        not isinstance(qe, int)
        or qe // 10000 < 2015
        or qe // 10000 > datetime.now().year + 1
        or VALID_QM.get(qe // 100 % 100) != qe % 100
    ):
        return "bad quarter-end"
    if not isinstance(con, (int, float)):
        return "PAT is not a number"
    (lo, hi), _sub = INSURERS[sym]
    if not (lo * 3 - 2000 <= con <= hi * 3):
        return f"PAT {con:.2f} cr outside plausible range {lo}..{hi} (unit mix-up? form wants Rs CRORE)"
    if not (len(ann) == 8 and ann.isdigit()):
        return "bad announcement date"
    if int(ann) < qe:
        return "announced before the quarter ended?"
    return None


def main():
    try:
        inbox = rpc("sw_kv_get", {"k": "INSURER_INBOX"})
    except Exception as ex:
        print(f"inbox pull failed ({ex}) — skipping this run, entries stay pending")
        return 0
    if not isinstance(inbox, list) or not any(
        isinstance(e, dict) and not e.get("applied") and not e.get("rejected") for e in inbox
    ):
        print("insurer inbox: nothing pending")
        return 0

    docs = json.load(open(DOCS_FUND, encoding="utf-8"))
    src = json.load(open(SRC_FUND, encoding="utf-8"))
    today = ist_today()
    n_applied = n_rejected = 0

    for e in reversed(inbox):  # oldest first, so a later correction of the same cell wins
        if not isinstance(e, dict) or e.get("applied") or e.get("rejected"):
            continue
        err = validate(e)
        if err:
            e["rejected"] = err
            n_rejected += 1
            print("REJECT {} {}: {}".format(e.get("sym"), e.get("qe"), err))
            continue
        sym, qe, con, ann, force = e["sym"], e["qe"], float(e["con"]), str(e["ann"]), bool(e.get("force"))
        cur = next((r for r in docs.get(sym, []) if r[0] == qe), None)
        if cur is not None and cur[3] is not None and not force:
            e["rejected"] = f"already filled ({cur[3]:.2f} cr) — tick overwrite to correct"
            n_rejected += 1
            print(f"REJECT {sym} {qe}: already filled")
            continue
        (_rng, sub) = INSURERS[sym]
        std = None if sub else con  # no-sub insurers store std == con (fetch_insurers convention)
        ch1 = set_cell(docs, sym, qe, con, ann, std=std, force=force)
        ch2 = set_cell(src, sym, qe, con, ann, std=std, force=force)
        if ch1 or ch2:
            e["applied"] = today
            n_applied += 1
            print("APPLY  {} {} con={:.2f} ann={}{}".format(sym, qe, con, ann, " (overwrite)" if force else ""))
        else:
            e["rejected"] = "no change (value identical?)"
            n_rejected += 1

    if n_applied:
        json.dump(docs, open(DOCS_FUND, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        json.dump(src, open(SRC_FUND, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        open(FLAG, "w").write(today)
        print(
            "filed %d entr%s into sf_fundamentals.json (+ scripts mirror), flagged rebuild"
            % (n_applied, "y" if n_applied == 1 else "ies")
        )
    if n_applied or n_rejected:
        try:
            ok = rpc("sw_kv_set", {"secret": WRITE, "k": "INSURER_INBOX", "payload": inbox})
            print("inbox statuses written back:", ok)
        except Exception as ex:
            print(
                f"WARN: could not write statuses back ({ex}) — entries may re-apply next run (harmless: fill-only + idempotent)"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
