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


"""
BULL_FLAG rescue experiment (evidence-first, no DB writes).
Replays history per symbol (step slices), detects bull flags under
4 parameter variants, grades each detection with the LIVE gate rule:
  trigger within 3 bars, stop-first path, WIN at +1R, 45-bar window.
PASS rule per variant: graded (W+L) >= 300 AND win-rate >= 60%.

Variants:
  current   : live params (gate says 56.0% -> DISABLED)
  tight_v1  : pole>=30%/25d, flag pb<=15%, <=20d, vcr<=0.85
  tight_v2  : pole>=35%/20d, pb 5-12%, <=15d, vcr<=0.80
  tight_v3  : pole>=30%/25d, pb 6-18%, <=20d, vcr<=0.90
All variants additionally require the flag NOT to drift up
(flag close drift <= +3%).

Usage:
  python bullflag_rescue.py [limit_symbols] [step]
"""
import sys

import db
import numpy as np
import pandas as pd
import patterns as P

PASS_MIN_GRADED = 300
PASS_MIN_WR = 0.60

VARIANTS = {
    "current": dict(P.PATTERN_PARAMS["BULL_FLAG"]),
    "tight_v1": {
        **P.PATTERN_PARAMS["BULL_FLAG"],
        "pole_min_gain": 0.30,
        "pole_max_days": 25,
        "flag_max_pullback": 0.15,
        "flag_max_days": 20,
        "max_vcr": 0.85,
    },
    "tight_v2": {
        **P.PATTERN_PARAMS["BULL_FLAG"],
        "pole_min_gain": 0.35,
        "pole_max_days": 20,
        "flag_min_pullback": 0.05,
        "flag_max_pullback": 0.12,
        "flag_max_days": 15,
        "max_vcr": 0.80,
    },
    "tight_v3": {
        **P.PATTERN_PARAMS["BULL_FLAG"],
        "pole_min_gain": 0.30,
        "pole_max_days": 25,
        "flag_min_pullback": 0.06,
        "flag_max_pullback": 0.18,
        "flag_max_days": 20,
        "max_vcr": 0.90,
    },
}


def detect_with(params, df, sauce):
    """Parameterized bull-flag detector + no-upward-drift rule.
    Returns dict(breakout, stop) or None."""
    p = params
    look = df.tail(p["lookback"]).copy().reset_index(drop=True)
    if len(look) < 55:
        return None
    hv = look["high"].values
    lv = look["low"].values
    rhi = int(np.argmax(hv[-35:])) + len(look) - 35
    rh = float(hv[rhi])
    fd = len(look) - 1 - rhi
    if fd < p["flag_min_days"] or fd > p["flag_max_days"]:
        return None
    ps = max(0, rhi - p["pole_max_days"])
    if rhi <= ps:
        return None
    pl = float(np.nanmin(lv[ps:rhi]))
    if pl <= 0:
        return None
    pg = rh / pl - 1.0
    if pg < p["pole_min_gain"]:
        return None
    fl = float(np.nanmin(lv[rhi:]))
    pb = rh / fl - 1.0
    if pb < p["flag_min_pullback"] or pb > p["flag_max_pullback"]:
        return None
    fc = look["close"].values[rhi:]
    if len(fc) >= 3 and fc[0] > 0 and (fc[-1] / fc[0] - 1.0) > 0.03:
        return None
    vcr = sauce.get("vcr")
    if vcr is not None and vcr > p["max_vcr"]:
        return None
    return {"breakout": rh, "stop": fl}


def grade(df, last_idx, breakout, stop):
    """Live gate grading on full history after last_idx."""
    h = df["high"].values
    l = df["low"].values
    n = len(df)
    target = breakout + 1.0 * (breakout - stop)
    trig = None
    for k in range(last_idx + 1, min(last_idx + 4, n)):
        if h[k] >= breakout:
            trig = k
            break
    if trig is None:
        return "EXPIRED" if (n - (last_idx + 1)) >= 3 else None
    for k in range(trig, min(trig + 46, n)):
        if l[k] <= stop:
            return "LOSS"
        if h[k] >= target:
            return "WIN"
    return "TIMEOUT" if (n - trig) >= 45 else None


def run(limit=300, step=10):
    conn = db.get_conn()
    syms = P._symbols(conn, limit)
    conn.close()
    stats = {name: {"n": 0, "w": 0, "l": 0} for name in VARIANTS}

    for i, sym in enumerate(syms, 1):
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume "
            "FROM prices_daily WHERE symbol=? ORDER BY date",
            (sym,),
        ).fetchall()
        conn.close()
        if len(rows) < 200:
            continue
        df = pd.DataFrame(list(rows), columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"])
        for j in range(150, len(df), step):
            slice_df = df.iloc[:j].reset_index(drop=True)
            sauce = P._secret_sauce(slice_df)
            for name, params in VARIANTS.items():
                det = detect_with(params, slice_df, sauce)
                if det is None:
                    continue
                out = grade(df, j - 1, det["breakout"], det["stop"])
                if out == "WIN":
                    stats[name]["w"] += 1
                    stats[name]["n"] += 1
                elif out == "LOSS":
                    stats[name]["l"] += 1
                    stats[name]["n"] += 1
        if i % 50 == 0:
            print(f"[BULLFLAG-RESCUE] progress {i}/{len(syms)}")

    print("[BULLFLAG-RESCUE] variant results (+1R, stop-first):")
    best = None
    for name, s in stats.items():
        gl = s["w"] + s["l"]
        wr = s["w"] / gl if gl else 0.0
        ok = gl >= PASS_MIN_GRADED and wr >= PASS_MIN_WR
        tag = "PASS" if ok else "FAIL"
        print(f"   {name:<10} graded={gl:<5} W/L={s['w']}/{s['l']}  WR={wr:.1%}  -> {tag}")
        if ok and (best is None or wr > best[1]):
            best = (name, wr, gl)
    if best:
        print(
            f"[BULLFLAG-RESCUE] VERDICT: apply '{best[0]}' "
            f"(WR {best[1]:.1%} on {best[2]} graded) -> RE-ENABLE"
        )
    else:
        print("[BULLFLAG-RESCUE] VERDICT: no variant passes -> keep BULL_FLAG DISABLED (kill)")
    return best


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    stp = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    run(limit=lim, step=stp)
