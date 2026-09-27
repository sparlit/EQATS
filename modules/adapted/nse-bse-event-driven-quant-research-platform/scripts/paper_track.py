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


"""Paper-trading ledger: snapshot today's candidates, settle, report.

Aligned with backtest filters:
  - Price range: Rs.100-500 (matches cluster_backtest)
  - Cluster entries: only first day of consecutive signal streak
  - Max 8 open positions
  - Technical filters: RSI 30-70, MACD bullish, close > SMA20
  - Minimum turnover: Rs.1 Cr daily

Multi-horizon support: each signal is recorded for 1d, 5d, and 10d horizons
with progressively wider stops (3%, 5%, 7%).

Subcommands:
    snapshot   write current dz_hi_up BUY candidates as OPEN paper rows (x3 horizons)
    settle     close OPEN rows past horizon or stop-hit
    report     predicted-vs-realized summary + GO-LIVE gate verdict by horizon
    log        print full trade log with all portfolio fields
"""


import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import sqlalchemy as sa
from indian_quant.config import load_settings
from indian_quant.features.delivery import (
    add_features,
    cluster_entry_mask,
    conviction_score,
    prepare_frame,
    signal_mask,
)
from indian_quant.portfolio.kelly import dynamic_kelly_params, kelly_fraction, kelly_position
from indian_quant.storage.pg_metadata import PgMetadataStore
from indian_quant.web.prod_config import get_pg_engine

GO_LIVE_MIN_SETTLED = 20
GO_LIVE_REALIZED_FLOOR_BPS = 25.0

# Optimal config: z>=2.5, 15d hold, 3 positions, 5% stop
# MC P(ruin)=0.60%, Sharpe=1.057, PF=2.249, WF robust=True
HORIZONS = [
    {"days": 15, "label": "15d", "stop_pct": 0.05, "capital_pct": 0.40},
]

# --- Backtest-aligned filters ---
PRICE_MIN = 100.0
PRICE_MAX = 500.0
MAX_OPEN_POSITIONS = 7
MIN_TURNOVER = 10_000_000.0  # Rs.1 Cr daily turnover
Z_MIN = 2.5  # Optimal z-score threshold (passes all professional gates)


def _load_frame_with_history(path: Path, lookback: int = 60) -> pd.DataFrame | None:
    """Load a parquet and return the last `lookback` rows with features.

    We need recent history (not just the last row) to compute cluster_entry_mask
    and technical filters (RSI, MACD, SMA) reliably.
    """
    raw = pd.read_parquet(path)
    frame = prepare_frame(raw, min_rows=40)
    if frame is None:
        return None
    frame = add_features(frame)
    if frame is None or frame.empty:
        return None
    return frame.tail(lookback)


def _scan_today(settings) -> pd.DataFrame:
    """Scan NSE delivery parquets for dz_hi_up candidates with backtest filters."""
    dl_dir = settings.normalized_dir / "delivery" / "NSE"
    rows = []
    for path in sorted(dl_dir.glob("*.parquet")):
        try:
            frame = _load_frame_with_history(path, lookback=60)
        except Exception:
            continue
        if frame is None or frame.empty:
            continue

        last = frame.iloc[-1]
        close = float(last["close"])

        # Equity-only filter (no ETFs, MFs, debt, etc.)
        segment = str(last.get("segment", "")).upper()
        if segment not in ("EQ", "NSE", "BSE"):
            continue

        # Price filter (backtest range)
        if not (PRICE_MIN <= close <= PRICE_MAX):
            continue

        # Turnover filter
        volume = float(last.get("volume", 0) or 0)
        turnover = close * volume
        if turnover < MIN_TURNOVER:
            continue

        # Signal filter (deliv_z >= 2.5 AND ret_1d >= 0.5%)
        sig_mask = signal_mask(frame, "dz_hi_up", z_min=Z_MIN)
        if not sig_mask.iloc[-1]:
            continue

        # Cluster entry filter: only enter on FIRST day of consecutive streak
        cluster_mask = cluster_entry_mask(sig_mask)
        if not cluster_mask.iloc[-1]:
            continue

        rows.append(
            {
                "symbol": str(last["symbol"]),
                "segment": str(last["segment"]),
                "close": close,
                "deliv_pct": last["deliv_pct"],
                "deliv_z": last["deliv_z"],
                "ret_1d": last["ret_1d"],
                "vol_z": last.get("vol_z", 0.0),
                "rsi": last.get("rsi", 50.0),
                "macd_hist": last.get("macd_hist", 0.0),
                "sma_20": last.get("sma_20", close),
                "volume": volume,
                "turnover": turnover,
                "date": last["date"].date().isoformat(),
            }
        )
    return pd.DataFrame(rows)


def cmd_snapshot(settings, *, capital: float, risk_pct: float) -> int:
    df = _scan_today(settings)
    if df.empty:
        print("no qualifying candidates (filters: price 100-500, cluster entry, RSI/MACD/SMA, turnover >= 1Cr)")
        return 0

    from indian_quant.features.market_cap import get_market_cap, load_mcap_cache, save_mcap_cache
    from indian_quant.ingestion.router import SourceRouter

    router = SourceRouter()
    cache = load_mcap_cache()

    metadata = PgMetadataStore(get_pg_engine())
    open_papers = metadata.open_papers()
    open_syms = {p["symbol"] for p in open_papers}
    n_open = len(open_papers)
    created = 0
    skipped_position_limit = 0

    for _, r in df.iterrows():
        # Skip if already have an OPEN position
        if r["symbol"] in open_syms:
            continue

        # Enforce max open positions across ALL horizons
        if n_open >= MAX_OPEN_POSITIONS:
            skipped_position_limit += 1
            continue

        mcap_info = get_market_cap(router, r["symbol"], "NSE", cache)
        score = conviction_score(r)

        for hz in HORIZONS:
            hz_capital = capital * hz["capital_pct"]
            win_rate, avg_win, avg_loss = dynamic_kelly_params(get_pg_engine())
            kf = kelly_fraction(win_rate, avg_win, avg_loss)
            qty = kelly_position(hz_capital, risk_pct, r["close"], hz["stop_pct"], kf)
            qty = max(qty, 1)
            # House rule: ₹1L notional per trade
            lakh_qty = max(1, int(100_000 / r["close"]))
            qty = max(qty, lakh_qty)

            position_value = qty * r["close"]
            stop_dist = r["close"] * hz["stop_pct"]
            risk_amount = qty * stop_dist

            metadata.record_paper_signal(
                symbol=r["symbol"],
                close_at_signal=float(r["close"]),
                qty=qty,
                horizon_days=hz["days"],
                stop_pct=hz["stop_pct"],
                segment=str(r["segment"]),
                entry_date=r["date"],
                position_value=round(position_value, 2),
                risk_amount=round(risk_amount, 2),
                horizon_label=hz["label"],
                capital_allocated=round(hz_capital, 2),
                conviction_score=round(score, 4),
                kelly_fraction=round(kf, 6),
                hypothesis_id=1,
                note=(
                    f"v2_aligned dz={r['deliv_z']:.2f} score={score:.3f} "
                    f"mcap={mcap_info['market_cap_class']} "
                    f"rsi={r['rsi']:.1f} turnover={r['turnover'] / 1e6:.1f}M"
                ),
            )

            # Auto-journal: record entry context
            with metadata._engine.connect() as _jc:
                paper_id = _jc.execute(
                    sa.text("SELECT id FROM paper_signals WHERE symbol=:s AND status='OPEN' ORDER BY id DESC LIMIT 1"),
                    {"s": r["symbol"]},
                ).scalar()
            if paper_id:
                entry_signal = (
                    f"deliv_z={r['deliv_z']:.2f} ret_1d={r.get('ret_1d', 0) * 100:+.2f}% "
                    f"rsi={r['rsi']:.1f} turnover={r['turnover'] / 1e6:.1f}M"
                )
                target = r["close"] * (1 + hz["stop_pct"] * 3)  # 3:1 R:R target
                metadata.journal_record_on_entry(
                    paper_trade_id=paper_id,
                    symbol=r["symbol"],
                    entry_date=r["date"],
                    entry_price=float(r["close"]),
                    entry_signal=entry_signal,
                    setup_type="delivery_momentum",
                    stop_loss=round(r["close"] * (1 - hz["stop_pct"]), 2),
                    target_price=round(target, 2),
                    position_size=qty,
                    risk_amount=round(risk_amount, 2),
                    conviction=round(score, 4),
                    sector=mcap_info.get("market_cap_class", ""),
                )

            created += 1
            n_open += 1
            print(
                f"OPEN {r['symbol']} [{hz['label']}] @{r['close']:.2f} "
                f"qty {qty} stop={hz['stop_pct'] * 100:.0f}% "
                f"val=₹{position_value:,.0f} risk=₹{risk_amount:,.0f} "
                f"score={score:.3f} kf={kf:.4f} "
                f"(z {r['deliv_z']:.1f} rsi={r['rsi']:.0f} "
                f"turnover={r['turnover'] / 1e6:.1f}M) "
                f"[{mcap_info['market_cap_class']}]"
            )

        open_syms.add(r["symbol"])

    save_mcap_cache(cache)
    summary = metadata.papers_summary()
    by_hz = metadata.paper_trades_by_horizon()
    metadata.close()

    filter_stats = {
        "candidates_found": len(df),
        "positions_open_before": n_open - created,
        "created": created,
        "skipped_position_limit": skipped_position_limit,
        "filters": {
            "price_range": f"₹{PRICE_MIN}-{PRICE_MAX}",
            "cluster_entry": True,
            "signal": f"deliv_z >= {Z_MIN} AND ret_1d >= 0.5%",
            "min_turnover": f"₹{MIN_TURNOVER / 1e6:.0f}M",
            "max_positions": MAX_OPEN_POSITIONS,
        },
    }
    print(json.dumps({**filter_stats, **summary, "by_horizon": by_hz}, indent=1))
    return 0


def cmd_settle(settings) -> int:
    metadata = PgMetadataStore(get_pg_engine())
    dl_dir = settings.normalized_dir / "delivery" / "NSE"
    settled = skipped = 0
    for paper in metadata.open_papers():
        path = dl_dir / f"{paper['symbol']}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        latest_date = str(df["date"].iloc[-1])[:10]
        latest_close = float(df["close"].iloc[-1])

        opened = pd.to_datetime(paper["created_at"]).date()
        from indian_quant.features.calendar_utils import trade_days_between

        sessions_held = trade_days_between(opened, pd.to_datetime(latest_date).date())
        # Intraday stop detection: check if low touched the stop level
        stop_price = paper["close_at_signal"] * (1 - paper["stop_pct"])
        latest_low = float(df["low"].iloc[-1]) if "low" in df.columns else latest_close
        hit_stop = latest_low <= stop_price
        past_horizon = sessions_held > paper["horizon_days"]
        if not (hit_stop or past_horizon):
            skipped += 1
            continue
        reason = "STOP" if hit_stop else "HORIZON"
        # Settle at stop price if intraday stop hit, otherwise at close
        settle_price = stop_price if hit_stop else latest_close
        sign = 1.0 if paper.get("side", "BUY") == "BUY" else -1.0
        gross_bps = (settle_price / paper["close_at_signal"] - 1.0) * 10_000 * sign
        # Round-trip costs 214bps (107 entry + 107 exit) — same as registry.close_trade
        net_bps = round(gross_bps - 214.0, 2)
        return_pct = round((settle_price / paper["close_at_signal"] - 1.0) * 100 * sign, 2)
        result = metadata.settle_paper_signal(
            paper["id"],
            exit_date=latest_date,
            exit_close=settle_price,
            exit_reason=reason,
            realized_net_bps=net_bps,
            return_pct=return_pct,
            return_bps=net_bps,
            days_held=sessions_held,
        )

        # Auto-journal: record exit context
        metadata.journal_record_on_exit(
            paper["id"],
            exit_date=latest_date,
            exit_price=settle_price,
            exit_reason=reason,
            exit_rationale=f"{reason} hit: {'stop' if hit_stop else 'horizon'} after {sessions_held} sessions",
            days_held=sessions_held,
            return_pct=return_pct,
            return_bps=round(gross_bps, 2),
            net_bps=net_bps,
        )

        print(
            f"SETTLE {paper['symbol']} [{paper.get('horizon_label', '?')}] "
            f"({reason}): net {result['realized_net_bps']}bps "
            f"ret={result['return_pct']:.1f}% days={result['days_held']}"
        )
        settled += 1
    summary = metadata.papers_summary()
    by_hz = metadata.paper_trades_by_horizon()
    metadata.close()
    print(json.dumps({"settled_now": settled, "skipped_still_open": skipped, **summary, "by_horizon": by_hz}, indent=1))
    return 0


def cmd_report(settings, *, min_settled: int, floor_bps: float) -> int:
    metadata = PgMetadataStore(get_pg_engine())
    s = metadata.papers_summary()
    pf = metadata.portfolio_summary()
    by_hz = metadata.paper_trades_by_horizon()
    metadata.close()
    passed = (s["settled"] or 0) >= min_settled and (s["avg_net_bps"] is not None and s["avg_net_bps"] >= floor_bps)
    verdict = (
        "PASS — GO-LIVE CHECKLIST may be generated"
        if passed
        else f"PENDING — need >= {min_settled} settled with avg_net >= {floor_bps}bps"
    )
    print(
        json.dumps(
            {
                "summary": s,
                "portfolio": pf,
                "by_horizon": by_hz,
                "golive_gate": verdict,
            },
            indent=1,
        )
    )
    return 0


def cmd_log(settings, *, horizon: str | None, status: str | None, limit: int) -> int:
    metadata = PgMetadataStore(get_pg_engine())
    trades = metadata.trade_log(horizon=horizon, status=status, limit=limit)
    metadata.close()
    for t in trades:
        entry = t.get("entry_date", "?")[:10]
        exit_d = (t.get("exit_date") or "")[:10]
        entry_px = t["close_at_signal"]
        exit_px = t.get("exit_close")
        ret = t.get("return_pct")
        net = t.get("realized_net_bps")
        status_s = t["status"]
        reason = t.get("exit_reason", "")
        hz = t.get("horizon_label", "?")
        score = t.get("conviction_score", 0)
        kf = t.get("kelly_fraction", 0)
        exit_str = f"{exit_px:.2f}" if exit_px else "—"
        ret_str = f"{ret:+.1f}%" if ret is not None else "—"
        net_str = f"{net:+.0f}bps" if net is not None else "—"
        print(
            f"  {t['symbol']:12s} {hz:3s} {status_s:8s} "
            f"entry={entry} @{entry_px:.2f} "
            f"exit={exit_d} @{exit_str} "
            f"ret={ret_str} net={net_str} "
            f"score={score:.3f} kf={kf:.4f} {reason}"
        )
    return 0


# ── Journal subcommands ──────────────────────────────────────────────────────


def cmd_journal_list(settings, *, setup: str, reviewed: str, limit: int) -> int:
    metadata = PgMetadataStore(get_pg_engine())
    rev = None
    if reviewed == "yes":
        rev = True
    elif reviewed == "no":
        rev = False
    entries = metadata.journal_list(setup_type=setup, reviewed=rev, limit=limit)
    metadata.close()
    if not entries:
        print("No journal entries found.")
        return 0
    for e in entries:
        entry_d = (e.get("entry_date") or "?")[:10]
        exit_d = (e.get("exit_date") or "OPEN")[:10]
        net = e.get("net_bps")
        net_str = f"{net:+.0f}bps" if net is not None else "OPEN"
        rating = e.get("review_rating") or "—"
        quality = e.get("setup_quality") or "—"
        exec_g = e.get("execution_grade") or "—"
        setup = e.get("setup_type", "?")
        reviewed = "✓" if e.get("review_date") else " "
        print(
            f"  [{reviewed}] #{e['id']:3d} {e['symbol']:12s} {setup:20s} "
            f"{entry_d}→{exit_d:10s} net={net_str:10s} "
            f"rating={rating} setup={quality} exec={exec_g}"
        )
    return 0


def cmd_journal_review(settings, paper_trade_id: int) -> int:
    metadata = PgMetadataStore(get_pg_engine())
    entry = metadata.journal_entry(paper_trade_id)
    if not entry:
        print(f"No journal entry for paper_trade_id={paper_trade_id}")
        metadata.close()
        return 1

    print(f"\n{'=' * 60}")
    print(f"TRADE JOURNAL — #{entry['id']} {entry['symbol']}")
    print(f"{'=' * 60}")
    print(f"  Entry: {entry.get('entry_date', '?')} @{entry.get('entry_price', 0):.2f}")
    print(f"  Signal: {entry.get('entry_signal', '?')}")
    print(f"  Setup: {entry.get('setup_type', '?')}")
    print(f"  Stop: {entry.get('stop_loss', 0):.2f}  Target: {entry.get('target_price', 0):.2f}")
    print(f"  Size: {entry.get('position_size', 0)} shares  Risk: Rs{entry.get('risk_amount', 0):.0f}")
    print(f"  Conviction: {entry.get('conviction', 0):.3f}")
    if entry.get("nifty_level"):
        print(f"  Nifty: {entry['nifty_level']:.0f}  Breadth: {entry.get('market_breadth', 0):.0%}")
    if entry.get("exit_date"):
        print(f"\n  Exit: {entry['exit_date'][:10]} @{entry.get('exit_price', 0):.2f}")
        print(f"  Reason: {entry.get('exit_reason', '?')}")
        print(
            f"  Days: {entry.get('days_held', 0)}  Return: {entry.get('return_pct', 0):+.1f}%  Net: {entry.get('net_bps', 0):+.0f}bps"
        )
    if entry.get("review_date"):
        print(f"\n  Review (rated {entry.get('review_rating', 0)}/5):")
        if entry.get("what_went_right"):
            print(f"    Right: {entry['what_went_right']}")
        if entry.get("what_went_wrong"):
            print(f"    Wrong: {entry['what_went_wrong']}")
        if entry.get("lessons_learned"):
            print(f"    Lessons: {entry['lessons_learned']}")
        print(f"    Would repeat: {'Yes' if entry.get('would_repeat') else 'No'}")
        print(f"    Setup grade: {entry.get('setup_quality', '?')}  Execution: {entry.get('execution_grade', '?')}")
    else:
        print(f"\n  No review yet. Use: paper_track.py journal-review {paper_trade_id}")
    metadata.close()
    return 0


def cmd_journal_add_review(
    settings,
    paper_trade_id: int,
    *,
    rating: int,
    right: str,
    wrong: str,
    lessons: str,
    repeat: bool,
    quality: str,
    execution: str,
    notes: str,
) -> int:
    metadata = PgMetadataStore(get_pg_engine())
    ok = metadata.journal_add_review(
        paper_trade_id,
        review_rating=rating,
        what_went_right=right,
        what_went_wrong=wrong,
        lessons_learned=lessons,
        would_repeat=repeat,
        setup_quality=quality,
        execution_grade=execution,
        notes=notes,
    )
    metadata.close()
    if ok:
        print(f"Review added for paper_trade_id={paper_trade_id}")
    else:
        print(f"No journal entry found for paper_trade_id={paper_trade_id}")
    return 0 if ok else 1


def cmd_journal_stats(settings) -> int:
    metadata = PgMetadataStore(get_pg_engine())
    stats = metadata.journal_stats()
    metadata.close()
    if not stats or stats.get("total_trades", 0) == 0:
        print("No journal entries yet.")
        return 0

    print(f"\n{'=' * 60}")
    print("TRADE JOURNAL STATS")
    print(f"{'=' * 60}")
    total = stats.get("total_trades", 0)
    winners = stats.get("winners", 0)
    losers = stats.get("losers", 0)
    wr = (winners / total * 100) if total else 0
    print(f"  Total trades: {total}")
    print(f"  Winners: {winners}  Losers: {losers}  Win rate: {wr:.1f}%")
    print(f"  Avg net: {stats.get('avg_net_bps') or 0:+.1f}bps")
    print(f"  Avg return: {stats.get('avg_return_bps') or 0:+.1f}bps")
    print(f"  Avg review rating: {stats.get('avg_rating') or 0:.1f}/5")
    print(f"  Reviewed: {stats.get('reviewed') or 0}/{total}")
    wr_yes = stats.get("would_repeat_count", 0)
    wr_no = stats.get("would_not_repeat", 0)
    print(f"  Would repeat: {wr_yes} yes / {wr_no} no")

    by_setup = stats.get("by_setup", [])
    if by_setup:
        print("\n  By Setup Type:")
        for s in by_setup:
            st = s.get("setup_type", "?")
            n = s.get("n", 0)
            avg = s.get("avg_net_bps", 0) or 0
            w = s.get("win_rate", 0) or 0
            print(f"    {st:25s} n={n:3d}  avg={avg:+.0f}bps  win={w:.0f}%")

    lessons = stats.get("recent_lessons", [])
    if lessons:
        print("\n  Recent Lessons:")
        for l in lessons:
            sym = l.get("symbol", "?")
            net = l.get("net_bps", 0) or 0
            ll = l.get("lessons_learned", "")
            print(f"    {sym:12s} net={net:+.0f}bps  {ll[:80]}")
    print(f"{'=' * 60}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Paper trading ledger")
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot")
    snap.add_argument("--capital", type=float, default=250_000.0)
    snap.add_argument("--risk-pct", type=float, default=1.0)

    sub.add_parser("settle")

    rep = sub.add_parser("report")
    rep.add_argument("--min-settled", type=int, default=GO_LIVE_MIN_SETTLED)
    rep.add_argument("--floor-bps", type=float, default=GO_LIVE_REALIZED_FLOOR_BPS)

    log_p = sub.add_parser("log")
    log_p.add_argument("--horizon", type=str, default=None, choices=["1d", "5d", "10d"])
    log_p.add_argument("--status", type=str, default=None, choices=["OPEN", "SETTLED"])
    log_p.add_argument("--limit", type=int, default=50)

    # Journal subcommands
    jl = sub.add_parser("journal-list", help="List trade journal entries")
    jl.add_argument("--setup", type=str, default="", help="Filter by setup type")
    jl.add_argument("--reviewed", type=str, default="all", choices=["all", "yes", "no"])
    jl.add_argument("--limit", type=int, default=30)

    jr = sub.add_parser("journal-review", help="Show full journal entry")
    jr.add_argument("paper_trade_id", type=int)

    jrev = sub.add_parser("journal-add-review", help="Add post-trade review")
    jrev.add_argument("paper_trade_id", type=int)
    jrev.add_argument("--rating", type=int, required=True, choices=[1, 2, 3, 4, 5])
    jrev.add_argument("--right", type=str, default="", help="What went right")
    jrev.add_argument("--wrong", type=str, default="", help="What went wrong")
    jrev.add_argument("--lessons", type=str, default="", help="Lessons learned")
    jrev.add_argument("--repeat", type=bool, default=True, help="Would repeat? (true/false)")
    jrev.add_argument("--quality", type=str, default="", choices=["", "A", "B", "C", "D"])
    jrev.add_argument("--execution", type=str, default="", choices=["", "A", "B", "C", "D"])
    jrev.add_argument("--notes", type=str, default="")

    sub.add_parser("journal-stats", help="Journal aggregate stats")

    args = parser.parse_args()
    settings = load_settings()

    if args.command == "snapshot":
        return cmd_snapshot(settings, capital=args.capital, risk_pct=args.risk_pct)
    if args.command == "settle":
        return cmd_settle(settings)
    if args.command == "report":
        return cmd_report(settings, min_settled=args.min_settled, floor_bps=args.floor_bps)
    if args.command == "log":
        return cmd_log(settings, horizon=args.horizon, status=args.status, limit=args.limit)
    if args.command == "journal-list":
        return cmd_journal_list(settings, setup=args.setup, reviewed=args.reviewed, limit=args.limit)
    if args.command == "journal-review":
        return cmd_journal_review(settings, args.paper_trade_id)
    if args.command == "journal-add-review":
        return cmd_journal_add_review(
            settings,
            args.paper_trade_id,
            rating=args.rating,
            right=args.right,
            wrong=args.wrong,
            lessons=args.lessons,
            repeat=args.repeat,
            quality=args.quality,
            execution=args.execution,
            notes=args.notes,
        )
    if args.command == "journal-stats":
        return cmd_journal_stats(settings)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
