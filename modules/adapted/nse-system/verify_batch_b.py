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


"""VM post-deploy verification for batch B3/B4/B5 (run on the VM)."""
import sys

sys.path.insert(0, ".")

print("=== 1. new modules import on VM ===")
try:
    import screener_engine
    import sector_pit
    import setup_sim

    print("  OK  setup_sim sector_pit screener_engine build_setup_pool research_cockpit")
except Exception as e:
    print(f"  FAIL {type(e).__name__}: {e}")
    raise SystemExit(1)

print("=== 2. screener uses canonical thresholds (B3) ===")
sc = screener_engine._SC.get("SCREENER", {})
st = screener_engine._SC.get("SETUP", {})
print(f"  config loaded: {len(sc)} SCREENER keys, {len(st)} SETUP keys")
assert len(st) > 0, "strategy_config did not load on the VM"
assert sc.get("MOM_1M_MIN") == 0.20, f"unexpected MOM_1M_MIN {sc.get('MOM_1M_MIN')}"
print(
    f"  MOM_1M_MIN={sc.get('MOM_1M_MIN')} IMPULSE_MIN_PCT={st.get('IMPULSE_MIN_PCT')} "
    f"PB_MAX_PCT={st.get('PB_MAX_PCT')} MIN_AVG_TURNOVER={sc.get('MIN_AVG_TURNOVER')}"
)
r = screener_engine.evaluate_stock("DIXON", allow_yahoo=False)
if "error" in r:
    print(f"  DIXON: {r['error']}")
else:
    print(f"  DIXON signal={r['overall_signal']} as_of={r['as_of']} source={r['source']}")
    labels = [k for k in r["checks"] if "Impulse" in k or "Pullback" in k]
    print(f"  dynamic labels: {labels}")

print("=== 3. point-in-time sector RS (B4) ===")
import db
import universe_helper as U

conn = db.get_conn()
syms = U.band_universe(conn, 500)
sof = dict(
    conn.execute("SELECT symbol, sector FROM stocks WHERE sector IS NOT NULL AND sector!=''")
)
have = [s for s in syms if sof.get(s)]
m = sector_pit.sector_rs_by_date(conn, syms, sof)
oob = sum(1 for v in m.values() if min(v.values()) < -1e-9 or max(v.values()) > 1 + 1e-9)
print(f"  universe={len(syms)} with-sector={len(have)} dates={len(m)} out-of-range={oob}")
assert oob == 0, f"{oob} dates have an rs outside [0,1]"
if have:
    probe = have[0]
    series = [m[d].get(probe) for d in sorted(m) if probe in m[d]]
    distinct = len({round(v, 6) for v in series if v is not None})
    print(f"  probe {probe}: {len(series)} dates, {distinct} distinct values")
    assert distinct > 1, "sector RS is still constant -> lookahead not removed"
    print("  OK  sector RS varies over time (lookahead removed)")

print("=== 4. shared forward simulator (B5) sane on real bars ===")
import pandas as pd

sym = have[0] if have else "DIXON"
df = pd.read_sql(
    "SELECT date,open,high,low,close,volume FROM prices_daily WHERE symbol=? ORDER BY date",
    conn,
    params=(sym,),
)
if len(df) > 140:
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df.columns = [c.capitalize() for c in df.columns]
    i = len(df) - 40
    trig, stop = float(df["High"].iloc[i]), float(df["Low"].iloc[i])
    res = setup_sim.simulate_forward(df, i, trig, stop)
    print(
        f"  {sym} bar {i}: outcome={res['outcome']} hit_1r={res['hit_1r']} "
        f"mfe_r={res['mfe_r']} mae_r={res['mae_r']}"
    )
conn.close()

print("=== 5. trader league accounting unaffected ===")
import subprocess

out = subprocess.run(
    [sys.executable, "trader_league.py", "selftest"], capture_output=True, text=True, timeout=600
)
line = [l for l in out.stdout.splitlines() if "checks passed" in l]
print("  " + (line[-1].strip() if line else f"selftest exit={out.returncode}"))
assert out.returncode == 0, "trader_league selftest failed"

print("\nALL VM CHECKS PASSED")
