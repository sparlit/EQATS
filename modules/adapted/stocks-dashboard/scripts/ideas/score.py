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


"""Score every published idea against prices: return since the call close and the best close since.

Usage: python3 scripts/ideas/score.py
Reads docs/ideas/ideas.json, writes docs/ideas/track.json. Prices come from BSE per-scrip history,
back-adjusted for bonus/split (bse.adjusted_history). Call close = close of the call date (the routine
stores it when it publishes); if missing it is the first close on or after the call date.

Two rules keep a bad network from destroying a good scorecard (both added 2026-09-24 after two runs
in a row had to hand-restore track.json, runbook 144e):

  1. FALLBACK. The per-scrip price endpoint is on api.bseindia.com, which BSE's edge can refuse for a
     whole network while www.bseindia.com still serves the daily bhavcopy. When the api fails, every
     unpriced idea is re-scored from the bhavcopies instead, in ONE pass over the dates. Such a row is
     marked `source: bhavcopy` and carries `adj_note`, because corporate actions are on the api too:
     a bonus or split is only caught by the one-day-gap rule, never by the official record.
  2. NEVER OVERWRITE A PRICED ROW WITH AN ERROR. The previous track.json is read first. If an idea
     cannot be priced this run but was priced before, the old row is carried forward marked
     `stale: true` with `stale_reason` and `stale_since`, and it still counts in the summary. An
     error row is written only for an idea that has never been priced.
"""
import datetime
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bse
import ist

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "..", "docs", "ideas")


def row_from(idea, rows, events, source):
    """Build a scorecard row from a price series already back-adjusted and sorted oldest first."""
    call = datetime.date.fromisoformat(idea["call_date"])
    after = [r for r in rows if r["date"] >= call]
    if not after:
        return {"idea_id": idea["id"], "scrip": idea["scrip"], "status": "no prices yet"}
    base = after[0]
    base_close = base["close"]
    if not base_close:
        return {"idea_id": idea["id"], "scrip": idea["scrip"], "status": "no prices yet"}
    peak = max(after, key=lambda r: r["close"])
    last = after[-1]
    out = {
        "idea_id": idea["id"],
        "scrip": idea["scrip"],
        "ticker": idea.get("ticker"),
        "name": idea.get("name"),
        "call_date": base["date"].isoformat(),
        "call_close": round(base_close, 2),
        "last_date": last["date"].isoformat(),
        "last_close": round(last["close"], 2),
        "ret_pct": round((last["close"] / base_close - 1) * 100, 1),
        "peak_date": peak["date"].isoformat(),
        "peak_close": round(peak["close"], 2),
        "peak_pct": round((peak["close"] / base_close - 1) * 100, 1),
        "days": (last["date"] - base["date"]).days,
        "adj_events": [f"{ex.isoformat()} x{f:g} {lab}" for ex, f, lab in events if ex >= call],
        "status": "ok",
    }
    if source != "api":
        out["source"] = source
        out["adj_note"] = (
            "priced from the daily bhavcopy because api.bseindia.com was unreachable; "
            "BSE's corporate-action record is on the same blocked host, so a bonus or split "
            "is caught only by the one-day-gap rule"
        )
    return out


def nse_only(idea):
    """An idea on a name with no BSE scrip code (NSE Emerge SME and other NSE-only listings)."""
    return idea.get("exchange") == "NSE" or not str(idea.get("scrip") or "").strip().isdigit()


def score_from_nse(idea):
    """Price an NSE-only idea from NSE's daily bhavcopies. A bonus or split after the call is caught by
    the one-day-gap rule only (no corporate-action record is read), so the row says so."""
    call = datetime.date.fromisoformat(idea["call_date"])
    sym = (idea.get("nse") or idea.get("ticker") or "").strip().upper()
    hist = bse.nse_bhav_history([sym], call - datetime.timedelta(days=10))
    rows = hist.get(sym) or []
    if not rows:
        raise RuntimeError(f"no NSE bhavcopy rows for {sym}")
    rows, events = bse.apply_adjustments(rows, [])
    out = row_from(idea, rows, events, "nse-bhavcopy")
    out["adj_note"] = (
        "priced from NSE daily bhavcopies (NSE-only listing); a bonus or split after the call "
        "is caught only by the one-day-gap rule"
    )
    return out


def score_idea(idea):
    """Price one idea from the per-scrip endpoint. Raises if that host is unreachable."""
    if nse_only(idea):
        return score_from_nse(idea)
    call = datetime.date.fromisoformat(idea["call_date"])
    rows, events = bse.adjusted_history(idea["scrip"], d_from=call - datetime.timedelta(days=10))
    return row_from(idea, rows, events, "api")


def score_from_bhavcopy(ideas):
    """Price a batch of ideas from the daily bhavcopies. One pass over the dates fills them all."""
    if not ideas:
        return {}
    first = min(datetime.date.fromisoformat(it["call_date"]) for it in ideas)
    hist = bse.bhav_history([it["scrip"] for it in ideas], first - datetime.timedelta(days=10))
    out = {}
    for it in ideas:
        rows = hist.get(str(it["scrip"]).strip()) or []
        if not rows:
            out[it["id"]] = None
            continue
        rows, events = bse.apply_adjustments(rows, [])
        out[it["id"]] = row_from(it, rows, events, "bhavcopy")
    return out


def previous_rows():
    fn = os.path.join(DOCS, "track.json")
    if not os.path.exists(fn):
        return {}, None
    try:
        old = json.load(open(fn))
    except Exception:
        return {}, None
    return {r["idea_id"]: r for r in (old.get("rows") or []) if r.get("idea_id")}, old.get(
        "updated"
    )


def carry_forward(prev, reason, updated):
    """Reuse a previously priced row rather than replacing it with an error. Marked, never silent."""
    row = dict(prev)
    row["stale"] = True
    row["stale_reason"] = reason
    row.setdefault("stale_since", prev.get("stale_since") or updated or "unknown")
    return row


def main():
    fn = os.path.join(DOCS, "ideas.json")
    if not os.path.exists(fn):
        print("no ideas.json yet")
        return
    ideas = json.load(open(fn)).get("ideas", [])
    prev, prev_updated = previous_rows()

    rows, retry, errs = {}, [], {}
    for it in ideas:
        try:
            rows[it["id"]] = score_idea(it)
        except Exception as e:
            errs[it["id"]] = str(e)
            retry.append(it)

    fallback = 0
    retry = [it for it in retry if not nse_only(it)]
    if retry:
        print(
            f"{len(retry)} idea(s) could not be priced from api.bseindia.com; trying the bhavcopy route"
        )
        try:
            got = score_from_bhavcopy(retry)
        except Exception as e:
            print(f"bhavcopy fallback failed too ({str(e)[:120]})")
            got = {}
        for it in retry:
            r = got.get(it["id"])
            if r and r.get("status") == "ok":
                rows[it["id"]] = r
                fallback += 1

    stale = 0
    out_rows = []
    for it in ideas:
        r = rows.get(it["id"])
        if r and r.get("status") == "ok":
            out_rows.append(r)
            continue
        # Not priced this run. Keep the last good row rather than destroying the scorecard.
        p = prev.get(it["id"])
        why = errs.get(it["id"]) or (r or {}).get("status") or "not priced this run"
        if p and p.get("status") == "ok":
            out_rows.append(carry_forward(p, why[:200], prev_updated))
            stale += 1
        elif r:
            out_rows.append(r)
        else:
            out_rows.append({"idea_id": it["id"], "scrip": it["scrip"], "status": f"error: {why}"})

    ok = [r for r in out_rows if r.get("status") == "ok"]
    summary = {}
    if ok:
        summary = {
            "count": len(ok),
            "median_ret": round(statistics.median([r["ret_pct"] for r in ok]), 1),
            "mean_ret": round(statistics.mean([r["ret_pct"] for r in ok]), 1),
            "up": sum(1 for r in ok if r["ret_pct"] > 0),
            "median_peak": round(statistics.median([r["peak_pct"] for r in ok]), 1),
            "hit_20": sum(1 for r in ok if r["peak_pct"] >= 20),
            "hit_50": sum(1 for r in ok if r["peak_pct"] >= 50),
            "stale": stale,
            "from_bhavcopy": fallback,
        }
    out = {"updated": ist.stamp(), "summary": summary, "rows": out_rows}
    json.dump(out, open(os.path.join(DOCS, "track.json"), "w"), indent=1)
    print(
        "scored",
        len(out_rows),
        "ideas;",
        len(ok),
        "priced",
        f"({fallback} via bhavcopy, {stale} carried forward stale);",
        summary,
    )


if __name__ == "__main__":
    main()
