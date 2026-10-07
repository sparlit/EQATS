from __future__ import annotations

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


"""Gate 1: cluster portfolio backtest with professional quant metrics.

Usage:
    python scripts/cluster_backtest.py [--hold 10 --price-max 500 ...]
    python scripts/cluster_backtest.py --full   # run Monte Carlo + walk-forward
"""


import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from indian_quant.config import load_settings
from indian_quant.research import ExperimentTracker
from indian_quant.research import portfolio_backtest as pb
from indian_quant.storage import MetadataStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate-1 cluster portfolio backtest")
    parser.add_argument("--signal", default="dz_hi_up")
    parser.add_argument(
        "--signals",
        default=None,
        help="Comma-separated extra signals to backtest per-signal "
        "(e.g. dz_hi_up,dz_hi_dn,spike_70,streak3). "
        "Results go into the 'by_signal' section of the JSON.",
    )
    parser.add_argument("--hold", type=int, default=15)
    parser.add_argument("--stop-pct", type=float, default=0.05)
    parser.add_argument("--price-min", type=float, default=100.0)
    parser.add_argument("--price-max", type=float, default=500.0)
    parser.add_argument("--max-positions", type=int, default=3)
    parser.add_argument("--capital", type=float, default=25_000.0)
    parser.add_argument("--risk-pct", type=float, default=1.0)
    parser.add_argument("--min-turnover", type=float, default=10_000_000.0)
    parser.add_argument("--no-cluster", action="store_true")
    parser.add_argument("--z-min", type=float, default=2.5)
    parser.add_argument("--use-conviction", action="store_true")
    parser.add_argument("--use-kelly", action="store_true")
    parser.add_argument(
        "--use-tech-filters",
        action="store_true",
        default=False,
        help="Apply RSI/MACD/SMA filters (default: False for 100-500 range)",
    )
    parser.add_argument("--no-tech-filters", action="store_false", dest="use_tech_filters")
    parser.add_argument("--use-trailing-stop", action="store_true")
    parser.add_argument("--trailing-stop-pct", type=float, default=0.03)
    parser.add_argument(
        "--use-indian-costs",
        action="store_true",
        default=True,
        help="Use detailed Indian cost breakdown (default: True)",
    )
    parser.add_argument("--no-indian-costs", action="store_false", dest="use_indian_costs")
    parser.add_argument(
        "--slippage-bps", type=float, default=10.0, help="Slippage in bps per side (default: 10)"
    )
    parser.add_argument(
        "--impact-bps", type=float, default=5.0, help="Impact cost in bps per side (default: 5)"
    )
    parser.add_argument(
        "--full", action="store_true", help="Run Monte Carlo + walk-forward analysis"
    )
    parser.add_argument("--mc-sims", type=int, default=1000, help="Monte Carlo simulation count")
    parser.add_argument("--wf-splits", type=int, default=5, help="Walk-forward splits")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    frames = pb.load_frames(settings.normalized_dir / "delivery" / "NSE", min_rows=40)
    print(f"symbols loaded: {len(frames)}")

    cfg = pb.StrategyConfig(
        signal=args.signal,
        price_min=args.price_min,
        price_max=args.price_max,
        min_turnover=args.min_turnover,
        hold_days=args.hold,
        stop_pct=args.stop_pct,
        max_positions=args.max_positions,
        capital=args.capital,
        risk_pct=args.risk_pct,
        cluster_entries=not args.no_cluster,
        z_min=args.z_min,
        use_conviction=args.use_conviction,
        use_kelly=args.use_kelly,
        use_tech_filters=args.use_tech_filters,
        slippage_bps=args.slippage_bps,
        impact_bps=args.impact_bps,
        use_trailing_stop=args.use_trailing_stop,
        trailing_stop_pct=args.trailing_stop_pct,
        use_indian_costs=args.use_indian_costs,
    )
    result = pb.run_portfolio(frames, cfg)

    # Print summary with all new metrics
    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    s = result.summary
    print(f"  Trades:           {s['n_trades']}")
    print(f"  Net Expectancy:   {s['net_expectancy_bps']:.2f} bps")
    print(f"  Win Rate:         {s['win_rate']:.1%}")
    print(f"  Profit Factor:    {s['profit_factor']:.3f}")
    print(f"  Payoff Ratio:     {s['payoff_ratio']:.3f}")
    print(f"  Expectancy (R):   {s['expectancy_r']:.3f}")
    print(f"  Max Drawdown:     {s['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe Ratio:     {s['sharpe_ratio']:.3f}")
    print(f"  Sortino Ratio:    {s['sortino_ratio']:.3f}")
    print(f"  Calmar Ratio:     {s['calmar_ratio']:.3f}")
    print(f"  SQN:              {s['sqn']:.3f}")
    print(f"  K-Ratio:          {s['k_ratio']:.3f}")
    print(f"  Ann Return:       {s['ann_return_pct']:.2f}%")
    print(f"  Avg Win:          {s['avg_win_bps']:.1f} bps")
    print(f"  Avg Loss:         {s['avg_loss_bps']:.1f} bps")
    print(f"  Avg MFE:          {s['avg_mfe_bps']:.1f} bps")
    print(f"  Avg MAE:          {s['avg_mae_bps']:.1f} bps")
    print(f"  Exit Efficiency:  {s['avg_exit_efficiency']:.1%}")
    print(f"  Tail Ratio:       {s['tail_ratio']:.3f}")
    print(f"  Max Win Streak:   {s['max_win_streak']}")
    print(f"  Max Loss Streak:  {s['max_loss_streak']}")
    print(f"  Total P&L:        ₹{s['total_pnl']:,.0f}")
    print(f"  Final Equity:     ₹{s['final_equity']:,.0f}")
    print(f"  Exit Reasons:     {s['exit_reasons']}")
    print("=" * 60)

    # Monte Carlo + Walk-Forward (optional)
    mc_result = None
    wf_result = None
    if args.full:
        print("\nRunning Monte Carlo bootstrap...")
        mc_result = pb.monte_carlo_bootstrap(
            result.trades,
            n_simulations=args.mc_sims,
            seed=42,
            starting_capital=args.capital,
        )
        print(f"  Simulations: {mc_result.get('n_simulations', 0)}")
        print(f"  P(ruin):     {mc_result.get('probability_of_ruin', 0):.2%}")
        print(f"  Launch OK:   {mc_result.get('launch_criteria_met', False)}")
        if "summary" in mc_result:
            ms = mc_result["summary"]
            print(f"  PnL 5th:     ₹{ms.get('pnl_5th', 0):,.0f}")
            print(f"  PnL Median:  ₹{ms.get('pnl_median', 0):,.0f}")
            print(f"  PnL 95th:    ₹{ms.get('pnl_95th', 0):,.0f}")
            print(f"  MaxDD 95th:  {ms.get('max_dd_95th', 0):.2f}%")
            print(f"  Sharpe 5th:  {ms.get('sharpe_5th', 0):.3f}")

        print("\nRunning walk-forward analysis...")
        wf_result = pb.walk_forward_analysis(frames, cfg, n_splits=args.wf_splits)
        if "error" not in wf_result:
            agg = wf_result.get("aggregate", {})
            deg = wf_result.get("degradation", {})
            stab = wf_result.get("stability", {})
            print(f"  Windows:     {wf_result.get('n_windows', 0)}")
            print(f"  Mean bps:    {agg.get('mean_net_bps', 0):.2f}")
            print(f"  Std bps:     {agg.get('std_net_bps', 0):.2f}")
            print(f"  Degradation: {deg.get('degradation_pct', 0):.1f}%")
            print(f"  Robust:      {deg.get('is_robust', False)}")
            print(f"  Stable:      {stab.get('is_stable', False)}")
            print(f"  CV:          {stab.get('coefficient_of_variation', 0):.3f}")
        else:
            print(f"  Error: {wf_result['error']}")

    # Per-signal backtests (hypothesis-wise metrics, no MC/WF per signal)
    by_signal: dict = {}
    if args.signals:
        for sig_name in [s.strip() for s in args.signals.split(",") if s.strip()]:
            if sig_name == args.signal:
                by_signal[sig_name] = result.summary
                continue
            try:
                sig_cfg = pb.StrategyConfig(
                    signal=sig_name,
                    price_min=args.price_min,
                    price_max=args.price_max,
                    min_turnover=args.min_turnover,
                    hold_days=args.hold,
                    stop_pct=args.stop_pct,
                    max_positions=args.max_positions,
                    capital=args.capital,
                    risk_pct=args.risk_pct,
                    cluster_entries=not args.no_cluster,
                    z_min=args.z_min,
                    use_conviction=args.use_conviction,
                    use_kelly=args.use_kelly,
                    use_tech_filters=args.use_tech_filters,
                    slippage_bps=args.slippage_bps,
                    impact_bps=args.impact_bps,
                    use_trailing_stop=args.use_trailing_stop,
                    trailing_stop_pct=args.trailing_stop_pct,
                    use_indian_costs=args.use_indian_costs,
                )
                sig_res = pb.run_portfolio(frames, sig_cfg)
                by_signal[sig_name] = sig_res.summary
                print(
                    f"  [{sig_name}] trades={sig_res.summary['n_trades']} "
                    f"net={sig_res.summary['net_expectancy_bps']:.1f}bps "
                    f"win={sig_res.summary['win_rate']:.1%}"
                )
            except Exception as e:
                by_signal[sig_name] = {"error": str(e)}
                print(f"  [{sig_name}] ERROR: {e}")

    # Record experiment
    metadata = MetadataStore(settings.storage.metadata_dsn)
    tracker = ExperimentTracker(metadata)
    run_id = tracker.record(kind="cluster_backtest", config=result.config, metrics=result.summary)
    metadata.close()

    # Save results
    out_dir = Path("docs/research/generated")
    out_dir.mkdir(parents=True, exist_ok=True)
    trades_json = [
        {
            "symbol": t.symbol,
            "segment": t.segment,
            "entry": str(t.entry_date),
            "entry_px": t.entry_px,
            "qty": t.qty,
            "exit": str(t.exit_date),
            "exit_px": t.exit_px,
            "gross_bps": t.gross_bps,
            "net_bps": t.net_bps,
            "reason": t.reason,
            "days_held": t.days_held,
            "mfe": t.mfe,
            "mae": t.mae,
            "pnl": t.pnl,
            "cost_bps": t.cost_bps,
        }
        for t in result.trades
    ]
    (out_dir / "cluster_backtest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "summary": result.summary,
                "equity_curve": [[str(d), round(v, 2)] for d, v in result.equity_curve],
                "trades": trades_json,
                "monte_carlo": mc_result,
                "walk_forward": wf_result,
                "by_signal": by_signal,
            },
            indent=1,
            default=str,
        )
    )

    # Gate evaluation
    gates = {
        "n_trades>=30": s["n_trades"] >= 30,
        "net>0": (s["net_expectancy_bps"] or -1) > 0,
        "maxDD<15%": s["max_drawdown_pct"] < 15,
        "sharpe>0": s.get("sharpe_ratio", 0) > 0,
        "profit_factor>1": s.get("profit_factor", 0) > 1,
    }
    if mc_result and "error" not in mc_result:
        gates["mc_ruin<1%"] = mc_result.get("probability_of_ruin", 1) < 0.01
        gates["mc_launch"] = mc_result.get("launch_criteria_met", False)
    if wf_result and "error" not in wf_result:
        gates["wf_robust"] = wf_result.get("degradation", {}).get("is_robust", False)

    print("\nGATES:")
    all_pass = True
    for gate, passed in gates.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {gate}: {status}")
        if not passed:
            all_pass = False

    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
