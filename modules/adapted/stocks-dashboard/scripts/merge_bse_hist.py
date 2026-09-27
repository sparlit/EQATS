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
     [--empty <outdir>/empty.json] [--unfetched <outdir>/unfetched.json]
     (the two sidecars are read from the manifest's directory when not given explicitly)

STUCK-NAME FIX (2026-09-23, see bse_hist_prep.py): a scrip whose window rendered no filing never
reached the manifest, so this merge never advanced it and it was re-picked every run forever. The
prep now writes two sidecars and this merge advances them too:
  empty.json      BSE confirmed the window holds no result filing → step past it (oldest→frm,
                  fails+1 — the same rule as a read that landed nothing)
  unfetched.json  filings were listed but none could be downloaded/rendered → ufails+1, and step past
                  only after MAX_UFAIL consecutive runs (dead attachment ≠ transient download error)
IDEMPOTENCY GUARD: a ledger entry is advanced only while its stored `oldest` still equals the
`oldest` the prep saw (or it has none yet). A re-run of the same merge, or a second merge racing on
the same scrip, would otherwise find its quarters already on file, land nothing, and wrongly step the
name past the window it just filled. Data writes stay fill-only either way.
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_bse_fund as bf

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "_bse_fund_hist.json")
MAX_FAIL = 3  # consecutive windows that yield nothing (read or confirmed-empty) → done
MAX_UFAIL = 3  # consecutive runs whose listed filings could not be fetched/rendered → step past


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def _arg(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else None


def _sidecar(explicit, man_path, name):
    path = explicit or (os.path.join(os.path.dirname(os.path.abspath(man_path)), name) if man_path else None)
    return json.load(open(path, encoding="utf-8")) if path and os.path.exists(path) else []


def main():
    out_path = sys.argv[1]
    man_path = _arg("--manifest")
    out = json.load(open(out_path, encoding="utf-8"))
    manifest = json.load(open(man_path, encoding="utf-8")) if man_path and os.path.exists(man_path) else []
    man = {str(m["scrip"]): m for m in manifest}  # frm/oldest/floor per scrip
    empty = [e for e in _sidecar(_arg("--empty"), man_path, "empty.json") if str(e["scrip"]) not in man]
    unfet = [e for e in _sidecar(_arg("--unfetched"), man_path, "unfetched.json") if str(e["scrip"]) not in man]

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

    def fresh(scrip, m):
        """Guard: advance only while the ledger still sits where the prep saw it (0/missing = none yet)."""
        o = (hist.get(scrip) or {}).get("oldest")
        return not o or int(o) == int(m.get("oldest", -1))

    def step_past(scrip, m, fails):
        floor = int(m.get("floor", 20200101))
        frm = int(m.get("frm", floor))
        done = frm <= floor + 300 or fails >= MAX_FAIL  # newoldest == frm
        hist[scrip] = {"oldest": frm, "fails": fails, "done": bool(done)}

    guarded = 0
    # read path: every scrip that had at least one filing rendered
    for scrip, m in man.items():
        if not fresh(scrip, m):
            guarded += 1
            continue
        floor = int(m.get("floor", 20200101))
        frm = int(m.get("frm", floor))
        got = landed.get(scrip) or []
        h = hist.get(scrip) or {}
        if got:
            newoldest, fails = min(got), 0
        else:
            newoldest, fails = frm, h.get("fails", 0) + 1  # nothing here → step past the window
        done = newoldest <= floor + 300 or frm <= floor or fails >= MAX_FAIL
        hist[scrip] = {"oldest": newoldest, "fails": fails, "done": bool(done)}

    # BSE-confirmed empty windows → step past (the stuck-name fix)
    n_empty = 0
    for m in empty:
        scrip = str(m["scrip"])
        if not fresh(scrip, m):
            guarded += 1
            continue
        step_past(scrip, m, (hist.get(scrip) or {}).get("fails", 0) + 1)
        n_empty += 1

    # listed but unfetchable → count; step past only after MAX_UFAIL consecutive runs
    n_uf = n_uf_step = 0
    for m in unfet:
        scrip = str(m["scrip"])
        if not fresh(scrip, m):
            guarded += 1
            continue
        h = dict(hist.get(scrip) or {})
        if m.get("run") and h.get("urun") == m["run"]:  # this exact prep run was already counted —
            guarded += 1  # oldest doesn't move here, so the oldest
            continue  # guard alone can't stop a double count
        uf = h.get("ufails", 0) + 1
        n_uf += 1
        if uf >= MAX_UFAIL:
            step_past(scrip, m, h.get("fails", 0) + 1)
            n_uf_step += 1
        else:
            h.update(oldest=int(m["oldest"]), fails=h.get("fails", 0), done=False, ufails=uf, urun=m.get("run"))
            hist[scrip] = h

    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    data["updated"] = ist.strftime("%Y-%m-%d %H:%M IST")
    json.dump(data, open(bf.OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(hist, open(HIST, "w"))
    print(
        "merge_bse_hist: %d scrips read, +%d historical quarters across %d scrips | %d empty window(s) "
        "stepped past | %d unfetchable counted (%d stepped past at %d) | %d skipped by guard"
        % (len(man), sum(len(v) for v in landed.values()), len(landed), n_empty, n_uf, n_uf_step, MAX_UFAIL, guarded)
    )


if __name__ == "__main__":
    main()
