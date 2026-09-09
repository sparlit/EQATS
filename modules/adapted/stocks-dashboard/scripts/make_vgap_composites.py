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
"""Tile the per-quarter net-profit crops produced by bse_vision (VPDIR=_vgap) into a few
composite PNGs for efficient vision reading. Each composite stacks up to ROWS labelled crops;
prints a JSON map composite_file -> [{sym,qe,unit,slot}] so the reader knows what each row is.

Run: python -X utf8 make_vgap_composites.py
"""
import json
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
VP = os.path.join(HERE, os.environ.get("VPDIR", "_vgap"))
ROWS = 10  # crops per composite


def main():
    man = json.load(open(os.path.join(VP, "manifest.json")))
    # one entry per crop file present
    items = [m for m in man if os.path.exists(os.path.join(VP, m["img"]))]
    items.sort(key=lambda m: (m["sym"], m["qe"]))
    comp_map = {}
    batch = []
    ci = 0

    def flush(batch, ci):
        imgs = []
        for slot, m in enumerate(batch):
            im = cv2.imread(os.path.join(VP, m["img"]))
            if im is None:
                continue
            im = cv2.resize(im, (1500, int(im.shape[0] * 1500 / im.shape[1])))
            bar = np.full((34, 1500, 3), 20, np.uint8)
            cv2.putText(
                bar,
                "slot %d | %s %d | unit=%s" % (slot, m["sym"], m["qe"], m.get("unit", "?")),
                (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
            )
            imgs.append(np.vstack([bar, im, np.full((4, 1500, 3), 120, np.uint8)]))
        if not imgs:
            return
        fn = "comp_%02d.png" % ci
        cv2.imwrite(os.path.join(VP, fn), np.vstack(imgs))
        comp_map[fn] = [
            {"slot": s, "sym": m["sym"], "qe": m["qe"], "unit": m.get("unit", "?")} for s, m in enumerate(batch)
        ]

    for m in items:
        batch.append(m)
        if len(batch) >= ROWS:
            flush(batch, ci)
            ci += 1
            batch = []
    if batch:
        flush(batch, ci)
    json.dump(comp_map, open(os.path.join(VP, "comp_map.json"), "w"), indent=0)
    print("wrote %d composites from %d crops -> _vgap/comp_*.png + comp_map.json" % (len(comp_map), len(items)))


if __name__ == "__main__":
    main()
