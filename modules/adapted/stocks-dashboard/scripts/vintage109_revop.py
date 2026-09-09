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
"""HEAL THE ROW, NOT THE CELL — rev/op alongside every by-product PAT heal.

Same gate: NSE's timely as-filed page supplies the target, and an independent reader (BSE detres
for std revenue/op, MC for either basis) must reproduce it before the slot moves.
memory: feedback-heal-the-row-not-the-cell
"""
import json
import os
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SLOT = {"rev_std": 0, "rev_con": 1, "op_std": 2, "op_con": 3, "pat_std": 4, "pat_con": 5}


def near(a, b, ab=0.35, rl=0.005):
    return a is not None and b is not None and abs(a - b) <= max(ab, abs(b) * rl)


def main():
    a = json.load(open(os.path.join(HERE, "_vintage109_adjud.json")))["cells"]
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    heals = [r for r in a.values() if r["verdict"] in ("HEAL", "HEAL-PAIR")]
    props, cnt = [], Counter()
    for r in heals:
        rrow = (revop.get(r["sym"]) or {}).get(str(r["qe"])) or []
        mc = r.get("mc") or {}
        for field, nsek, detk, mcks in (
            ("rev", "nse_rev", "detres_rev", ("rev_ops", "rev_total")),
            ("op", "nse_op", "detres_op", ("op_pre", "op_post")),
        ):
            name = "{}_{}".format(field, r["basis"])
            s = SLOT[name]
            cur = rrow[s] if len(rrow) > s else None
            tgt = r.get(nsek)
            if cur is None:
                cnt[f"{field}: slot empty"] += 1
                continue
            if tgt is None:
                cnt[f"{field}: NSE line unreadable"] += 1
                continue
            if near(cur, tgt):
                cnt[f"{field}: slot already as-filed"] += 1
                continue
            det = r.get(detk) if r["basis"] == "std" else None
            mcv = [mc.get(x) for x in mcks if mc.get(x) is not None]
            if det is not None and near(det, cur):
                cnt[f"{field}: detres BACKS the stored slot - vetoed"] += 1
                continue
            # READER PRECEDENCE, same as the PAT gate. MC serves a RESTATED vintage 42% of the
            # time, so "MC agrees with the stored slot" often just means the slot holds the
            # restated row — which is the defect, not a defence. It may not veto a target that
            # BOTH exchange readers reproduce to the paisa. DLF Mar-2016 is the case that forced
            # this: PAT healed to the as-filed 1088.94 while revenue stayed on the restated
            # 1968.19 because MC holds 1968.15, leaving HALF A ROW on each vintage — exactly what
            # feedback-heal-the-row-not-the-cell warns about.
            two_exchange = det is not None and abs(det - tgt) <= max(0.02, abs(tgt) * 0.0002)
            if any(near(v, cur) for v in mcv) and not two_exchange:
                cnt[f"{field}: MC backs the stored slot - vetoed"] += 1
                continue
            ev = []
            if det is not None and near(det, tgt):
                ev.append("DETRES")
            if any(near(v, tgt) for v in mcv):
                ev.append("MC")
            if not ev:
                cnt[f"{field}: no independent reader on the target"] += 1
                continue
            cnt[f"{field}: PROPOSED"] += 1
            props.append(
                {
                    "sym": r["sym"],
                    "qe": str(r["qe"]),
                    "basis": ("std" if name == "rev_std" else "con" if name == "rev_con" else name),
                    "was": cur,
                    "fixed": round(tgt, 2),
                    "_field": field,
                    "_ev": {
                        "evidence": ev,
                        "nse": tgt,
                        "detres": det,
                        "mc": mcv,
                        "nse_seq": r["nse_seq"],
                        "nse_filed": r["nse_filed"],
                        "gap_qe_to_nsefiled": r["gap_qe_to_nsefiled"],
                    },
                }
            )
    for k, n in sorted(cnt.items()):
        print("  %-48s %d" % (k, n))
    print("\nrev/op slot proposals: %d (%s)" % (len(props), dict(Counter(p["basis"] for p in props))))
    json.dump({"revop": props}, open(os.path.join(HERE, "_vintage109_revop.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
