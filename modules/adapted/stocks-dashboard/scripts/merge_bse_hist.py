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
"""MERGE stage for the BSE historical-fundamentals routine.

Applies what the cloud routine's subagents read from the historical P&L PNGs (bse_hist_prep.py) into
docs/bse_fundamentals.json — FILL-ONLY (never overwrites a quarter already on file), quarters only
(no year columns), only quarters older than the scrip's oldest-stored and >= floor — then advances the
resumable ledger scripts/_bse_fund_hist.json so the next run walks deeper (or skips an empty window).

Subagent output (one object per company, quarters keyed by period-end YYYYMMDD):
  [{"sym":"CIANAGRO","scrip":519477,"ok":true,"basis":"S",
    "quarters":{"20220630":{"rev":49.29,"pat":0.46},"20220331":{"rev":60.65,"pat":-2.01}, …}}, …]

Run: python -X utf8 scripts/merge_bse_hist.py <subagent_out.json> --manifest <outdir>/manifest.json
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_bse_fund as bf

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "_bse_fund_hist.json")


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def main():
    out_path = sys.argv[1]
    man_path = sys.argv[sys.argv.index("--manifest") + 1] if "--manifest" in sys.argv else None
    out = json.load(open(out_path, encoding="utf-8"))
    manifest = json.load(open(man_path, encoding="utf-8")) if man_path and os.path.exists(man_path) else []
    man = {str(m["scrip"]): m for m in manifest}  # frm/oldest/floor per scrip

    data = json.loads(open(bf.OUT, encoding="utf-8").read()) if os.path.exists(bf.OUT) else {"px": {}}
    px = data.setdefault("px", {})
    hist = json.load(open(HIST)) if os.path.exists(HIST) else {}
    today_i = int(datetime.date.today().strftime("%Y%m%d"))

    landed = {}
    for it in out:
        if not it.get("ok"):
            continue
        scrip = str(it.get("scrip") or "")
        if not scrip:
            continue
        basis = it.get("basis", "S") or "S"
        m = man.get(scrip) or {}
        floor = int(m.get("floor", 20200101))
        oldest = int(m.get("oldest", 99999999))
        cur = px.setdefault(scrip, {})
        for qe, vals in (it.get("quarters") or {}).items():
            if not (str(qe).isdigit() and len(str(qe)) == 8):
                continue
            qei = int(qe)
            if not (floor <= qei < oldest and qei <= today_i):  # older than stored, above floor, sane
                continue
            if str(qe) in cur:  # fill-only
                continue
            pat = _num(vals.get("pat"))
            rev = _num(vals.get("rev"))
            if pat is None and rev is None:
                continue
            rec = {"pat": pat, "ann": 0, "basis": basis, "src": "vision-hist"}
            if rev is not None:
                rec["rev"] = rev
            cur[str(qe)] = rec
            landed.setdefault(scrip, []).append(qei)

    # advance the ledger for every scrip that was prepped this run
    for scrip, m in man.items():
        floor = int(m.get("floor", 20200101))
        oldest = int(m.get("oldest", 99999999))
        frm = int(m.get("frm", floor))
        got = landed.get(scrip) or []
        h = hist.get(scrip) or {}
        if got:
            newoldest, fails = min(got), 0
        else:
            newoldest, fails = frm, h.get("fails", 0) + 1  # nothing here → step past the window
        done = newoldest <= floor + 300 or frm <= floor or fails >= 3
        hist[scrip] = {"oldest": newoldest, "fails": fails, "done": bool(done)}

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    data["updated"] = ist.strftime("%Y-%m-%d %H:%M IST")
    json.dump(data, open(bf.OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(hist, open(HIST, "w"))
    print(
        "merge_bse_hist: %d scrips prepped, +%d historical quarters across %d scrips"
        % (len(man), sum(len(v) for v in landed.values()), len(landed))
    )


if __name__ == "__main__":
    main()
