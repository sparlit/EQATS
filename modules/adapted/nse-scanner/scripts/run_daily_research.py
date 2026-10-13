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


"""Offline progressive daily research and preserved Hull loss audit.

Run from repository root: python -m scripts.run_daily_research --help
Only the selected output directory is written. No source database migrations.
"""

import argparse
import hashlib
import json
import math
from dataclasses import asdict
from pathlib import Path

import pandas as pd
from daily_research.audit import audit_hull
from daily_research.data import load_sources
from daily_research.features import ResearchConfig, candidate_mask, features
from daily_research.replay import ExecutionConfig, metrics, replay


def write_json(path, value):
    # Convert Pandas/numpy nulls to strict JSON null, never NaN or Infinity.
    def clean(v):
        if isinstance(v, dict):
            return {str(k): clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        if isinstance(v, pd.Timestamp):
            return v.date().isoformat()
        if hasattr(v, "item"):
            return clean(v.item())
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return None
        return v

    path.write_text(json.dumps(clean(value), indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", type=Path, default=Path("nse_scanner.db"))
    p.add_argument("--snapshots", type=Path, default=Path("market_data/daily"))
    p.add_argument("--hull-state", type=Path, default=Path("pine_hull_state.json"))
    p.add_argument("--output", type=Path, default=Path("output/daily_research"))
    p.add_argument(
        "--symbols",
        nargs="+",
        help="Optional explicit smoke-test subset; not representative performance",
    )
    p.add_argument("--start", default="2026-01-01")
    p.add_argument(
        "--split", default="2026-06-01", help="Fixed chronological research/holdout boundary"
    )
    p.add_argument("--end", default=None)
    p.add_argument("--fee-bps", type=float, default=10)
    p.add_argument("--slippage-bps", type=float, default=5)
    p.add_argument(
        "--revised-exits",
        action="store_true",
        help="Separate experiment: structure trail, T1 breakeven, next-open deterioration exit",
    )
    args = p.parse_args()
    out = args.output.resolve()
    # Prevent a mistaken output path from clobbering deployed artifacts.
    root = (Path.cwd() / "output").resolve()
    if not out.is_relative_to(root) or out == root:
        p.error("--output must be a dedicated subdirectory of ./output")
    if out.exists() and any(out.iterdir()):
        p.error("Output already contains a run; choose a new directory to preserve evidence")
    if not args.start < args.split:
        p.error("--split must follow --start")
    cfg = ResearchConfig()
    execution = ExecutionConfig(
        fee_bps=args.fee_bps, slippage_bps=args.slippage_bps, trail=args.revised_exits
    )
    execution.validate()
    frames, benchmark, coverage = load_sources(args.db, args.snapshots, args.symbols)
    end = args.end or coverage["combined_price_end"]
    if not args.split <= end:
        p.error("--end must be on or after --split")
    calendar = sorted({str(x) for d in frames.values() for x in d.trade_date})
    variants = ("mature_control", "progressive", "with_weekly", "daily_location")
    scanners = ("Hull", "V3", "Momentum Ladder", "Penny")
    results = {
        f"{s}/{v}": {"trades": [], "open": [], "pending": [], "events": [], "signals": 0}
        for s in scanners
        for v in variants
    }
    latest, errors = [], []
    for i, (symbol, raw) in enumerate(frames.items()):
        if len(raw) < 112:
            continue
        try:
            d = features(raw, cfg, benchmark)
            last = d.loc[d.trade_date.le(end)].tail(1)
            if last.empty:
                continue
            row = last.iloc[0].to_dict()
            replay_cache = {}
            for scanner in scanners:
                masks = {v: candidate_mask(d, scanner, v, cfg) for v in variants}
                current = row["trade_date"].date().isoformat() == end
                technical = bool(masks["daily_location"].loc[last.index[0]]) and current
                latest.append(
                    {
                        "symbol": symbol,
                        "scanner": scanner,
                        **row,
                        "technical_candidate": technical,
                        "stale_price": not current,
                        "operational_entry_ready": False,
                        "eligibility": "NOT VALIDATED; DAILY TECHNICAL RESEARCH",
                        "planned_entry": row["trigger"] if technical else None,
                        "planned_stop": row["stop"] if technical else None,
                        "next": (
                            "Wait for fresh daily data"
                            if not current
                            else "Watch for next-session trigger; research only"
                            if technical
                            else "Watch for daily confirmation; research only"
                        ),
                    }
                )
                for variant, mask in masks.items():
                    key = f"{scanner}/{variant}"
                    results[key]["signals"] += int(
                        (mask & d.trade_date.ge(args.start) & d.trade_date.le(end)).sum()
                    )
                    if not mask.any():
                        continue
                    replay_frame = d.assign(enforce_room=variant == "daily_location")
                    # Run independent periods: training trades cannot cross into
                    # holdout, nor can future holdout outcomes tune training.
                    for label, start_day, end_day in (
                        (
                            "research",
                            args.start,
                            (pd.Timestamp(args.split) - pd.Timedelta(days=1)).date().isoformat(),
                        ),
                        ("holdout", args.split, end),
                    ):
                        cache_key = (mask.to_numpy().tobytes(), variant == "daily_location", label)
                        if cache_key not in replay_cache:
                            replay_cache[cache_key] = replay(
                                replay_frame,
                                mask,
                                symbol,
                                start=start_day,
                                end=end_day,
                                config=execution,
                                session_calendar=calendar,
                            )
                        r = replay_cache[cache_key]
                        for field in ("trades", "open", "pending", "events"):
                            results[key][field].extend(
                                {**item, "symbol": symbol, "period": label} for item in r[field]
                            )
        except (ValueError, KeyError) as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
        if (i + 1) % 100 == 0:
            print(f"Processed {i + 1}/{len(frames)} symbols", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "mode": "OFFLINE PAPER RESEARCH",
        "source_mutation": "NONE",
        "delivery": "NONE",
        "source_coverage": coverage,
        "config": asdict(cfg),
        "execution": asdict(execution),
        "start": args.start,
        "split": args.split,
        "end": end,
        "subset": args.symbols,
        "comparison": "COMMON TECHNICAL EXPERIMENTS, NOT REPLAY OF THE FOUR NATIVE STRATEGIES",
        "capital_model": "INDEPENDENT ONE-RISK-UNIT TRADES; NO PORTFOLIO RETURN/DRAWDOWN CLAIM",
        "data_limitations": [
            "Survivorship/security eligibility is not certified.",
            "Corporate actions not adjusted; >25% opening discontinuities frozen for review.",
            "Locked candles cannot fill; circuit limits and intraday sequence unavailable.",
            "Weekly permission uses completed weekly EMA/structure; not unavailable weekly Hybrid Hull.",
            "No intraday or TradingView dependency. Monthly filter excluded.",
            "Fundamentals, sector valuation and historical restrictions not silently passed.",
            "Holdout is exploratory on existing data, not a future independently collected validation.",
        ],
        "errors": errors,
    }
    manifest["configuration_hash"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest()
    manifest["engine_fingerprint"] = hashlib.sha256(
        b"".join(path.read_bytes() for path in sorted(Path("daily_research").glob("*.py")))
    ).hexdigest()
    manifest["hull_state_fingerprint"] = (
        hashlib.sha256(args.hull_state.read_bytes()).hexdigest()
        if args.hull_state.exists()
        else None
    )
    write_json(out / "manifest.json", manifest)
    write_json(out / "latest_candidates.json", latest)
    summary = {}
    for key, result in results.items():
        summary[key] = {
            "signals": result["signals"],
            "open_or_review": len(result["open"]),
            "pending": len(result["pending"]),
        }
        for label in ("research", "holdout"):
            trades = [t for t in result["trades"] if t["period"] == label]
            summary[key][label] = metrics(trades)
            summary[key][label]["by_setup"] = {
                s: metrics([t for t in trades if t["setup"] == s])
                for s in sorted({t["setup"] for t in trades})
            }
            summary[key][label]["by_weekly_permission"] = {
                s: metrics([t for t in trades if t["weekly_permission"] == s])
                for s in sorted({t["weekly_permission"] for t in trades})
            }
            summary[key][label]["by_entry_distance"] = {
                "near_ema21": metrics([t for t in trades if t["distance_ema_atr"] <= 0.5]),
                "intermediate": metrics([t for t in trades if 0.5 < t["distance_ema_atr"] <= 1.25]),
                "extended": metrics([t for t in trades if t["distance_ema_atr"] > 1.25]),
            }
        write_json(out / (key.replace("/", "_").replace(" ", "_") + ".json"), result)
    write_json(out / "comparison.json", summary)
    if args.hull_state.exists():
        state = json.loads(args.hull_state.read_text(encoding="utf-8"))
        write_json(out / "hull_recorded_audit.json", audit_hull(state, frames))
    rows = [
        "# Daily scanner research",
        "",
        "Offline only. No deployed rules changed. No TradingView dependency.",
        "",
        f"Data through {end}; holdout begins {args.split}. Costs: {args.fee_bps} bps fees + {args.slippage_bps} bps slippage per side.",
        "",
        "**These are technical experiments, not native scanner win rates.** Missing eligibility data prevents deployment qualification.",
        "",
        "| Research profile / variant | Holdout closed | Win rate | Expectancy (R) | Profit factor |",
        "|---|---:|---:|---:|---:|",
    ]

    def fmt(x):
        return "Unavailable" if x is None else f"{x:.2f}"

    for key, result in summary.items():
        m = result["holdout"]
        rows.append(
            f"| {key} | {m['closed_trades']} | {fmt(m['win_rate_pct'])} | {fmt(m['expectancy'])} | {fmt(m['profit_factor'])} |"
        )
    rows += [
        "",
        "Read manifest.json for data exclusions; hull_recorded_audit.json preserves recorded losses.",
        "No win-rate improvement or deployment readiness is established by this exploratory run.",
    ]
    (out / "REPORT.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(out), "coverage": coverage, "errors": len(errors)}, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
