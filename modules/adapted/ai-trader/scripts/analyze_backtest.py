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
Deep analysis of tick-replay backtest results.
Identifies concrete reasons for low RR, poor win rate, and profit leakage.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd


def analyze_risk(risk):
    path = f"backtest_results/trades_{risk}_risk.csv"
    if not os.path.exists(path):
        print(f"  {risk}: no data")
        return None
    df = pd.read_csv(path)
    if df.empty:
        print(f"  {risk}: empty")
        return None

    winners = df[df["pnl"] > 0]
    losers = df[df["pnl"] <= 0]
    avg_win = winners["pnl"].mean() if len(winners) else 0
    avg_loss = losers["pnl"].mean() if len(losers) else 0
    rr = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print(f"\n{'=' * 70}")
    print(
        f"  {risk.upper()} RISK  —  {len(df)} trades  |  WR {len(winners) / len(df) * 100:.0f}%  |  RR {rr:.2f}  |  P&L ₹{df['pnl'].sum():+,.0f}"
    )
    print(f"{'=' * 70}")

    # ── 1. Exit reason breakdown ─────────────────────────────────────────
    print("\n  1. EXIT REASONS:")
    for r, g in df.groupby("result"):
        w = (g["pnl"] > 0).sum()
        pct = len(g) / len(df) * 100
        print(
            f"     {r:15s}  {len(g):3d} ({pct:4.0f}%)  |  {w}W/{len(g) - w}L  |  avg ₹{g['pnl'].mean():+,.0f}  |  total ₹{g['pnl'].sum():+,.0f}"
        )

    # ── 2. SL hits — the biggest P&L drain ───────────────────────────────
    sl = df[df["result"] == "SL"]
    if not sl.empty:
        print("\n  2. SL ANALYSIS (biggest loss contributor):")
        print(
            f"     SL hits drain ₹{sl['pnl'].sum():+,.0f} ({abs(sl['pnl'].sum() / df['pnl'].sum()) * 100:.0f}% of total if profitable)"
        )
        print(f"     Avg SL loss: ₹{sl['pnl'].mean():+,.0f}  |  Max: ₹{sl['pnl'].min():+,.0f}")
        print(f"     Avg entry premium: ₹{sl['entry_premium'].mean():.0f}")
        print(f"     Avg sl_pct: {sl['sl_pct'].mean():.0%}")
        print(f"     Avg lot_size: {sl['lot_size'].mean():.0f}")
        for _, t in sl.iterrows():
            hold_min = "?"
            try:
                entry = pd.to_datetime(t["entry_time"])
                exit_ = pd.to_datetime(t["exit_time"])
                hold_min = f"{(exit_ - entry).total_seconds() / 60:.0f}m"
            except Exception:
                pass
            print(
                f"     → {str(t['entry_time'])[:16]} {t['direction']:4s} {t['strategy']:25s} "
                f"prem=₹{t['entry_premium']:.0f} sl={t['sl_pct']:.0%} lots={t['lot_size']} "
                f"hold={hold_min} pnl=₹{t['pnl']:+,.0f}"
            )

    # ── 3. Timeout analysis ──────────────────────────────────────────────
    to = df[df["result"] == "TIMEOUT"]
    if not to.empty:
        to_lose = to[to["pnl"] <= 0]
        print(f"\n  3. TIMEOUT ANALYSIS ({len(to)} trades, {len(to_lose)} losing):")
        print(f"     Losing timeouts drain ₹{to_lose['pnl'].sum():+,.0f}")
        print(f"     Avg losing timeout: ₹{to_lose['pnl'].mean():+,.0f}" if len(to_lose) > 0 else "")
        # Check: are timeouts close to breakeven? (means we should exit earlier)
        near_be = to[(to["pnl"].abs() / (to["entry_premium"] * to["lot_size"])) < 0.05]
        if len(near_be) > 0:
            print(f"     Near-breakeven timeouts (< 5% move): {len(near_be)} — potential early exit candidates")

    # ── 4. Trailing SL effectiveness ─────────────────────────────────────
    tsl = df[df["result"] == "TRAILING_SL"]
    if not tsl.empty:
        tsl_lose = tsl[tsl["pnl"] <= 0]
        print(f"\n  4. TRAILING SL ({len(tsl)} trades):")
        print(f"     Avg pnl: ₹{tsl['pnl'].mean():+,.0f}  |  {(tsl['pnl'] > 0).sum()}W/{(tsl['pnl'] <= 0).sum()}L")
        if len(tsl_lose) > 0:
            print(f"     Losing trailing stops: {len(tsl_lose)} — trail locks at breakeven but gives back profit?")
            print(f"     Avg losing TSL pnl: ₹{tsl_lose['pnl'].mean():+,.0f}")

    # ── 5. RR decomposition ──────────────────────────────────────────────
    print("\n  5. RISK-REWARD DECOMPOSITION:")
    print(f"     Avg winner:  ₹{avg_win:+,.0f}  ({len(winners)} trades)")
    print(f"     Avg loser:   ₹{avg_loss:+,.0f}  ({len(losers)} trades)")
    print(f"     Current RR:  {rr:.2f}")
    # What-if: if avg loser was capped
    if len(losers) > 0:
        capped_losses = losers["pnl"].clip(lower=losers["pnl"].quantile(0.25))
        new_avg_loss = capped_losses.mean()
        new_rr = abs(avg_win / new_avg_loss) if new_avg_loss != 0 else 0
        print(f"     If worst 25% losses capped: RR would be {new_rr:.2f}")
    # What-if: winners 20% bigger (tighter trailing or later exit)
    if rr > 0:
        needed_avg_win = abs(avg_loss) * 1.7
        pct_increase = (needed_avg_win / avg_win - 1) * 100 if avg_win > 0 else 0
        print(f"     To reach RR 1.7: avg winner needs to be ₹{needed_avg_win:+,.0f} (+{pct_increase:.0f}%)")

    # ── 6. Strategy-level problem detection ──────────────────────────────
    print("\n  6. STRATEGY PERFORMANCE:")
    for s, g in df.groupby("strategy"):
        w = (g["pnl"] > 0).sum()
        wr = w / len(g) * 100
        g_win = g[g["pnl"] > 0]
        g_lose = g[g["pnl"] <= 0]
        s_rr = abs(g_win["pnl"].mean() / g_lose["pnl"].mean()) if len(g_lose) > 0 and len(g_win) > 0 else 0
        flag = " ❌ DRAG" if g["pnl"].sum() < 0 and len(g) >= 3 else ""
        print(
            f"     {s:30s}  {len(g):3d} trades  WR={wr:4.0f}%  RR={s_rr:.2f}  "
            f"P&L=₹{g['pnl'].sum():+,.0f}  avg=₹{g['pnl'].mean():+,.0f}{flag}"
        )

    # ── 7. Direction analysis ────────────────────────────────────────────
    print("\n  7. DIRECTION ANALYSIS:")
    for d, g in df.groupby("direction"):
        w = (g["pnl"] > 0).sum()
        flag = " ❌ DRAG" if g["pnl"].sum() < -500 else ""
        print(f"     {d:4s}  {len(g)} trades  |  WR={w / len(g) * 100:.0f}%  |  P&L=₹{g['pnl'].sum():+,.0f}{flag}")

    # ── 8. Premium sizing analysis ───────────────────────────────────────
    print("\n  8. PREMIUM & LOT SIZING:")
    print(
        f"     Entry premium: mean=₹{df['entry_premium'].mean():.0f}  min=₹{df['entry_premium'].min():.0f}  max=₹{df['entry_premium'].max():.0f}"
    )
    print(
        f"     Lot size:      mean={df['lot_size'].mean():.0f}  min={df['lot_size'].min()}  max={df['lot_size'].max()}"
    )
    # Risk per trade
    df["risk_amount"] = df["entry_premium"] * df["sl_pct"] * df["lot_size"]
    print(f"     Risk per trade: mean=₹{df['risk_amount'].mean():,.0f}  max=₹{df['risk_amount'].max():,.0f}")

    # ── 9. Score vs outcome correlation ──────────────────────────────────
    print("\n  9. SCORE-OUTCOME CORRELATION:")
    if len(df) > 5:
        corr = df["final_score"].corr(df["pnl"])
        print(f"     Score-PnL correlation: {corr:.3f}" + (" (weak — score not predictive)" if abs(corr) < 0.2 else ""))
        # High score vs low score trades
        median_score = df["final_score"].median()
        high_score = df[df["final_score"] > median_score]
        low_score = df[df["final_score"] <= median_score]
        print(
            f"     Above median score ({median_score:.3f}): {len(high_score)} trades  P&L=₹{high_score['pnl'].sum():+,.0f}"
        )
        print(
            f"     Below median score ({median_score:.3f}): {len(low_score)} trades  P&L=₹{low_score['pnl'].sum():+,.0f}"
        )

    # ── 10. Hold time analysis ───────────────────────────────────────────
    try:
        df["hold_minutes"] = (
            pd.to_datetime(df["exit_time"]) - pd.to_datetime(df["entry_time"])
        ).dt.total_seconds() / 60
        print("\n  10. HOLD TIME:")
        print(
            f"      Winners avg hold:  {winners['hold_minutes'].mean() if 'hold_minutes' in df.columns else '?':.0f} min"
        )
        print(
            f"      Losers avg hold:   {losers['hold_minutes'].mean() if 'hold_minutes' in df.columns else '?':.0f} min"
        )
        print(f"      Max hold: {df['hold_minutes'].max():.0f} min")
    except Exception:
        pass

    return df


def main():
    print("\n" + "=" * 70)
    print("  BACKTEST DEEP DIVE — PROFITABILITY ANALYSIS")
    print("=" * 70)

    all_dfs = {}
    for risk in ["high", "medium", "low"]:
        result = analyze_risk(risk)
        if result is not None:
            all_dfs[risk] = result

    # ── Cross-profile comparison ─────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("  CROSS-PROFILE SUMMARY")
    print(f"{'=' * 70}")
    print(
        f"  {'Profile':<10s} {'Trades':>7s} {'WR':>6s} {'RR':>6s} {'P&L':>10s} {'AvgWin':>8s} {'AvgLoss':>8s} {'MaxDD':>8s}"
    )
    for risk, df in all_dfs.items():
        w = df[df["pnl"] > 0]
        l = df[df["pnl"] <= 0]
        rr = abs(w["pnl"].mean() / l["pnl"].mean()) if len(l) > 0 and len(w) > 0 else 0
        eq = df["pnl"].cumsum()
        dd = (eq - eq.cummax()).min()
        print(
            f"  {risk:<10s} {len(df):>7d} {len(w) / len(df) * 100:>5.0f}% {rr:>5.2f} "
            f"₹{df['pnl'].sum():>+9,.0f} ₹{w['pnl'].mean():>+7,.0f} ₹{l['pnl'].mean():>+7,.0f} ₹{dd:>+7,.0f}"
        )

    # ── Key findings ─────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print("  KEY FINDINGS & RECOMMENDATIONS")
    print(f"{'=' * 70}")

    if "high" in all_dfs:
        df = all_dfs["high"]
        sl = df[df["result"] == "SL"]
        to = df[df["result"] == "TIMEOUT"]
        tsl = df[df["result"] == "TRAILING_SL"]
        rl = df[df["result"] == "RL_EXIT"]
        tgt = df[df["result"] == "TARGET"]

        issues = []
        # Check SL drain
        if not sl.empty and sl["pnl"].sum() < -3000:
            issues.append(
                f"SL hits drain ₹{sl['pnl'].sum():+,.0f} — avg ₹{sl['pnl'].mean():+,.0f} per SL. "
                f"Consider tightening lot size on high-vol entries or using time-based SL reduction."
            )
        # Check timeout losses
        to_losses = to[to["pnl"] <= 0]
        if len(to_losses) > 2:
            issues.append(
                f"{len(to_losses)} losing timeouts draining ₹{to_losses['pnl'].sum():+,.0f}. "
                f"Reduce max_hold_bars or add breakeven-exit at 70% hold time."
            )
        # Check trailing SL
        tsl_losses = tsl[tsl["pnl"] <= 0]
        if len(tsl_losses) > 1:
            issues.append(
                f"{len(tsl_losses)} trailing SL exits at 0/negative P&L. "
                f"Trail lock is at breakeven — consider locking at +5% instead of 0%."
            )
        # Check CALL performance
        calls = df[df["direction"] == "CALL"]
        if len(calls) > 3 and calls["pnl"].sum() < 0:
            issues.append(
                f"CALL trades losing ₹{calls['pnl'].sum():+,.0f}. "
                f"CALL scoring may be too loose or ML prob threshold too low."
            )
        # Check strategy drags
        for s, g in df.groupby("strategy"):
            if g["pnl"].sum() < -1000 and len(g) >= 3:
                issues.append(
                    f"Strategy '{s}' is a drag: {len(g)} trades, ₹{g['pnl'].sum():+,.0f}. "
                    f"Consider raising score threshold for this strategy."
                )
        # Check RR
        w = df[df["pnl"] > 0]
        l = df[df["pnl"] <= 0]
        if len(w) > 0 and len(l) > 0:
            rr = abs(w["pnl"].mean() / l["pnl"].mean())
            if rr < 1.7:
                target_winners = tgt["pnl"].mean() if len(tgt) > 0 else 0
                rl_winners = rl[rl["pnl"] > 0]["pnl"].mean() if len(rl[rl["pnl"] > 0]) > 0 else 0
                issues.append(
                    f"RR={rr:.2f} < 1.7 target. Winners avg ₹{w['pnl'].mean():+,.0f} vs losers ₹{l['pnl'].mean():+,.0f}. "
                    f"TARGET exits avg ₹{target_winners:+,.0f}, RL exits avg ₹{rl_winners:+,.0f}. "
                    f"Need bigger targets or smaller losses."
                )

        if issues:
            for i, issue in enumerate(issues, 1):
                print(f"\n  {i}. {issue}")
        else:
            print("\n  No major issues detected.")

    print()


if __name__ == "__main__":
    main()
