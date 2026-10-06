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
"""TERP inputs for every RIGHTS issue in the corporate-action review (DATA_RUNBOOK §161g).

Policy (2026-07-10, user): every parseable rights issue is TERP-adjusted (rights_terp.json). The
review found rights ex-dates where the old ca_factor() guess baked a split fraction instead. This
gathers, from official NSE sources only, what a TERP needs and writes
scripts/ca_rights_terp_evidence.json:
  terms     the rights row itself (ratio B:A = B new shares per A held, premium) — NSE feed subject
  fv_now    current face value — NSE EQUITY_L.csv (listed companies only)
  fv_moves  every later face-value split/consolidation row on the NSE feed (to walk FV back in time)
  cum       raw close on the last cum-rights session — NSE bhavcopy (already in ca_review_evidence)
TERP = (A*cum + B*(fv_then + premium)) / (A + B); factor = TERP / cum. Nothing is computed when any
input is missing — the event stays unresolved and says which input.

Run (CI, after verify_ca_review.py): python3 scripts/verify_rights_terp.py
"""
import csv
import datetime
import io
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_argv = sys.argv
sys.argv = _argv[:1]
import build_fundamentals as F
import verify_ca_review as V

sys.argv = _argv

OUT = os.path.join(HERE, "ca_rights_terp_evidence.json")
RIGHTS_RE = re.compile(
    r"rights?\s*-?\s*(\d+)\s*:\s*(\d+)(?:.*?premium\s*(?:of\s*)?(?:r[se]\.?\s*)?([\d.]+))?", re.I
)
FV_RE = re.compile(
    r"(?:(?:f(?:ace)?\s*v(?:alue)?.*?(?:split|splt|spl\b|sub.?division))|consolidat).*?(?:r[se]\.?\s*)?([\d.]+)\s*/?-?\s*(?:per share\s*)?to\s*(?:r[se]\.?\s*)?([\d.]+)",
    re.I,
)


def equity_l(jar):
    for url in (
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        "https://archives.nseindia.com/content/equities/EQUITY_L.csv",
    ):
        try:
            txt = F._get(
                url,
                headers={"User-Agent": F.UA, "Referer": "https://www.nseindia.com/"},
                jar=jar,
                timeout=60,
            )
            rows = list(csv.DictReader(io.StringIO(txt)))
            if rows:
                key = next(k for k in rows[0] if "FACE" in k.upper())
                return {
                    r["SYMBOL"].strip(): float(r[key]) for r in rows if r.get(key, "").strip()
                }, url
        except Exception as e:
            str(e)[:60]
    return {}, "EQUITY_L unreachable"


def main():
    E = json.load(open(os.path.join(HERE, "ca_review_evidence.json")))["events"]
    jar = F.nse_jar()
    fvmap, fvsrc = equity_l(jar)
    out = []
    for e in E:
        rrows = [
            r
            for r in (e.get("nse") or {}).get("rows") or []
            if "right" in (r.get("subject") or "").lower() and not r.get("factor")
        ]
        if not rrows:
            continue
        s = e["sym"]
        ev = {
            k: e.get(k) for k in ("sym", "a", "b", "F", "raw", "adj_a", "adj_b", "raw_ratio_bhav")
        }
        ev["rights_rows"] = rrows
        m = RIGHTS_RE.search(rrows[0]["subject"])
        ev["terms"] = (
            {
                "B": int(m.group(1)),
                "A": int(m.group(2)),
                "premium": float(m.group(3)) if m.group(3) else None,
            }
            if m
            else None
        )
        ev["fv_now"] = fvmap.get(s)
        ev["fv_src"] = fvsrc
        # every face-value change AFTER the rights ex-date, from the NSE feed (both boards, all aliases)
        moves = []
        for board in ("equities", "sme"):
            st, rows = V.nse_rows(jar, s, board)
            time.sleep(0.35)
            for x in rows:
                ex = F.iso(x.get("exDate"))
                subj = x.get("subject") or ""
                mm = FV_RE.search(
                    re.sub(r"tor([se])", r" to r\1", subj)
                )  # "Rs10tors2" era spelling
                if ex and mm and int(ex) > e["b"]:
                    moves.append(
                        {
                            "ex": int(ex),
                            "from": float(mm.group(1)),
                            "to": float(mm.group(2)),
                            "subject": subj,
                        }
                    )
        ev["fv_moves"] = sorted(moves, key=lambda x: x["ex"])
        bh = (e.get("bhav") or {}).get(str(e["a"]))
        ev["cum"] = bh.get("close") if isinstance(bh, dict) else None
        miss = [k for k in ("terms", "fv_now", "cum") if not ev.get(k)]
        if (
            ev.get("terms")
            and ev["terms"]["premium"] is None
            and "premium" not in rrows[0]["subject"].lower()
        ):
            miss.append("premium not stated")
        if not miss:
            fv = ev["fv_now"]
            for mv in reversed(ev["fv_moves"]):
                fv = fv * mv["from"] / mv["to"]  # walk FV back to the rights date
            issue = fv + (ev["terms"]["premium"] or 0.0)
            A, Bn = ev["terms"]["A"], ev["terms"]["B"]
            terp = (A * ev["cum"] + Bn * issue) / (A + Bn)
            ev.update(
                {
                    "fv_then": round(fv, 4),
                    "issue_price": round(issue, 4),
                    "terp": round(terp, 4),
                    "terp_factor": round(terp / ev["cum"], 4),
                }
            )
        ev["missing"] = miss
        out.append(ev)
        print(
            "%-12s %d terms=%s fv_now=%s moves=%d cum=%s -> %s"
            % (
                s,
                e["b"],
                ev["terms"],
                ev["fv_now"],
                len(ev["fv_moves"]),
                ev["cum"],
                ev.get("terp_factor") or ("MISSING " + ",".join(miss)),
            ),
            flush=True,
        )
    json.dump(
        {
            "generated": datetime.datetime.utcnow().isoformat() + "Z",
            "equity_l": fvsrc,
            "events": out,
        },
        open(OUT, "w"),
        indent=0,
    )
    print("wrote %d rights events -> %s" % (len(out), OUT))


if __name__ == "__main__":
    main()
