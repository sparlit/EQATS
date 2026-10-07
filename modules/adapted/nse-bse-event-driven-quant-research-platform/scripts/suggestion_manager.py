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


"""Daily suggestion manager: auto-record signals at 1d/5d/10d horizons, settle, report.

Aligned with backtest filters:
  - Price range: Rs.100-500 (matches cluster_backtest)
  - Cluster entries: only first day of consecutive signal streak
  - Technical filters: RSI 30-70, MACD bullish, close > SMA20
  - Minimum turnover: Rs.1 Cr daily

Each dz_hi_up signal is recorded 3 times (one per horizon) with appropriate
stop-loss and target levels for each holding period.

Subcommands:
    record      Record today's signals as suggestions (x3 horizons)
    settle      Settle PENDING suggestions whose horizon has passed
    report      Show accuracy metrics by horizon + combined
"""


import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np
import pandas as pd
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

HORIZONS = [
    {
        "days": 1,
        "label": "1d",
        "stop_pct": 0.03,
        "target_pct": 0.02,
        "capital_pct": 0.25,
        "predicted_bps": 30.0,
    },
    {
        "days": 5,
        "label": "5d",
        "stop_pct": 0.05,
        "target_pct": 0.05,
        "capital_pct": 0.35,
        "predicted_bps": 60.0,
    },
    {
        "days": 10,
        "label": "10d",
        "stop_pct": 0.07,
        "target_pct": 0.08,
        "capital_pct": 0.40,
        "predicted_bps": 80.0,
    },
]

# --- Backtest-aligned filters ---
PRICE_MIN = 100.0
PRICE_MAX = 500.0
MIN_TURNOVER = 10_000_000.0  # Rs.1 Cr daily turnover


def _load_frame_with_history(path: Path, lookback: int = 60) -> pd.DataFrame | None:
    """Load a parquet and return the last `lookback` rows with features."""
    raw = pd.read_parquet(path)
    if raw.empty:
        return None
    frame = prepare_frame(raw, min_rows=min(20, len(raw)))
    if frame is None or frame.empty:
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

        # Signal filter with technical confirmation
        sig_mask = signal_mask(frame, "dz_hi_up")
        if not sig_mask.iloc[-1]:
            continue

        # Cluster entry filter: only first day of consecutive streak
        cluster_mask = cluster_entry_mask(sig_mask)
        if not cluster_mask.iloc[-1]:
            continue

        rows.append(
            {
                "symbol": str(last["symbol"]),
                "segment": str(last["segment"]),
                "close": close,
                "volume": volume,
                "deliv_pct": float(last["deliv_pct"]) if not pd.isna(last["deliv_pct"]) else None,
                "deliv_z": float(last["deliv_z"]) if not pd.isna(last["deliv_z"]) else None,
                "vol_z": float(last.get("vol_z", 0))
                if not pd.isna(last.get("vol_z", np.nan))
                else None,
                "ret_1d": float(last["ret_1d"]),
                "rsi": float(last.get("rsi", 50)) if not pd.isna(last.get("rsi", np.nan)) else 50.0,
                "macd_hist": float(last.get("macd_hist", 0))
                if not pd.isna(last.get("macd_hist", np.nan))
                else 0.0,
                "sma_20": float(last["sma_20"])
                if not pd.isna(last.get("sma_20", np.nan))
                else None,
                "turnover": turnover,
                "date": last["date"].date().isoformat(),
                "_atr": float(last.get("atr_14", 0))
                if not pd.isna(last.get("atr_14", np.nan))
                else 0,
            }
        )
    return pd.DataFrame(rows)


def cmd_record(settings, *, capital: float, risk_pct: float) -> int:
    from indian_quant.config.connections import check_data_freshness

    freshness = check_data_freshness(get_pg_engine())
    if not freshness["is_fresh"]:
        print(
            f"WARNING: Data stale — age={freshness['age_hours']}h, "
            f"today={freshness['today_count']}/{freshness['total_stocks']} stocks"
        )
    df = _scan_today(settings)
    if df.empty:
        print(
            "no qualifying candidates (filters: price 100-500, cluster entry, RSI/MACD/SMA, turnover >= 1Cr)"
        )
        return 0

    latest = df["date"].max()

    metadata = PgMetadataStore(get_pg_engine())

    existing = set()
    for s in metadata.suggestions_by_date(latest):
        existing.add(s["symbol"])

    created = 0

    from indian_quant.features.market_cap import get_market_cap, load_mcap_cache, save_mcap_cache
    from indian_quant.ingestion.router import SourceRouter

    router = SourceRouter()
    cache = load_mcap_cache()

    for _, r in df.iterrows():
        if r["symbol"] in existing:
            continue

        mcap_info = get_market_cap(router, r["symbol"], "NSE", cache)
        score = conviction_score(r)

        for hz in HORIZONS:
            hz_capital = capital * hz["capital_pct"]
            win_rate, avg_win, avg_loss = dynamic_kelly_params(get_pg_engine())
            kf = kelly_fraction(win_rate, avg_win, avg_loss)
            qty = kelly_position(hz_capital, risk_pct, r["close"], hz["stop_pct"], kf)
            if qty < 1:
                qty = 1

            atr = r.get("_atr", r["close"] * 0.03)
            entry_low = round(r["close"] - atr * 0.5, 2)
            entry_high = round(r["close"], 2)
            stop_loss = round(r["close"] * (1 - hz["stop_pct"]), 2)
            target = round(r["close"] * (1 + hz["target_pct"]), 2)

            sid = metadata.record_daily_suggestion(
                suggestion_date=latest,
                symbol=r["symbol"],
                segment=str(r["segment"]),
                signal_type="dz_hi_up",
                close_at_signal=float(r["close"]),
                deliv_pct=float(r["deliv_pct"]) if r["deliv_pct"] else None,
                deliv_z=float(r["deliv_z"]) if not pd.isna(r["deliv_z"]) else None,
                vol_z=float(r["vol_z"]) if r["vol_z"] and not pd.isna(r["vol_z"]) else None,
                entry_zone_low=entry_low,
                entry_zone_high=entry_high,
                stop_loss=stop_loss,
                target_price=target,
                horizon_days=hz["days"],
                qty_suggested=qty,
                conviction_score=round(score, 4),
                kelly_fraction=round(kf, 6),
                note=(
                    f"v2_aligned z={r['deliv_z']:.2f} score={score:.3f} "
                    f"mcap={mcap_info['market_cap_class']} "
                    f"rsi={r['rsi']:.1f} turnover={r['turnover'] / 1e6:.1f}M"
                ),
            )
            created += 1
            print(
                f"  #{sid} {r['symbol']} [{hz['label']}] @₹{r['close']:.2f} "
                f"qty={qty} stop=₹{stop_loss} target=₹{target} "
                f"score={score:.3f} kf={kf:.4f} "
                f"z={r['deliv_z']:.2f} [{mcap_info['market_cap_class']}]"
            )

    save_mcap_cache(cache)
    summary = metadata.suggestions_summary()
    by_hz = metadata.suggestions_by_horizon()
    metadata.close()
    print(json.dumps({"created_today": created, **summary, "by_horizon": by_hz}, indent=1))
    return 0


def cmd_settle(settings) -> int:
    metadata = PgMetadataStore(get_pg_engine())
    dl_dir = settings.normalized_dir / "delivery" / "NSE"
    settled_count = skipped = 0

    pending = metadata.pending_suggestions()

    for s in pending:
        sym = s["symbol"]
        path = dl_dir / f"{sym}.parquet"
        if not path.exists():
            continue

        df = pd.read_parquet(path, columns=["date", "close"])
        suggestion_date = s["suggestion_date"]

        after = df[pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d") > suggestion_date]
        if len(after) < s["horizon_days"]:
            skipped += 1
            continue

        exit_row = (
            after.iloc[s["horizon_days"] - 1] if len(after) >= s["horizon_days"] else after.iloc[-1]
        )
        exit_date = str(pd.to_datetime(exit_row["date"]).date())
        exit_close = float(exit_row["close"])

        entry_close = s["close_at_signal"]
        sign = 1.0 if s.get("direction", "BUY") == "BUY" else -1.0
        gross_bps = (exit_close / entry_close - 1.0) * 10_000 * sign
        net_bps = round(gross_bps - 107.0, 2)

        metadata.settle_daily_suggestion(
            s["id"],
            actual_exit_date=exit_date,
            actual_exit_close=exit_close,
            actual_return_bps=net_bps,
        )
        hz = f"{s['horizon_days']}d"
        hit = net_bps > 0
        print(f"  SETTLED {sym} [{hz}]: net {net_bps}bps ret={net_bps / 100:.2f}% hit={hit}")
        settled_count += 1

    summary = metadata.suggestions_summary()
    by_hz = metadata.suggestions_by_horizon()
    metadata.close()
    print(
        json.dumps(
            {
                "settled_now": settled_count,
                "skipped_insufficient_data": skipped,
                **summary,
                "by_horizon": by_hz,
            },
            indent=1,
        )
    )
    return 0


def cmd_report(settings) -> int:
    metadata = PgMetadataStore(get_pg_engine())
    s = metadata.suggestions_summary()
    by_hz = metadata.suggestions_by_horizon()

    gate_pass = (s["realized"] or 0) >= 20 and (
        s["avg_realized_net_bps"] is not None and s["avg_realized_net_bps"] > 25
    )

    verdict = (
        "PASS — ready for live consideration"
        if gate_pass
        else (
            f"PENDING — need >= 20 realized with avg_net >= +25bps "
            f"(currently {s['realized']} realized)"
        )
    )

    con_str = settings.storage.metadata_dsn.removeprefix("sqlite:///")
    import sqlite3

    con = sqlite3.connect(con_str)
    by_type = con.execute("""
        SELECT signal_type, horizon_days, COUNT(*),
               AVG(actual_return_bps), SUM(hit)*1.0/COUNT(*)
        FROM daily_suggestions WHERE status='REALIZED'
        GROUP BY signal_type, horizon_days
        ORDER BY AVG(actual_return_bps) DESC
    """).fetchall()
    con.close()

    print(
        json.dumps(
            {
                "summary": s,
                "golive_gate": verdict,
                "by_horizon": by_hz,
                "by_type_and_horizon": [
                    {
                        "type": t[0],
                        "horizon": f"{t[1]}d",
                        "n": t[1],
                        "avg_net_bps": round(t[3], 1) if t[3] else None,
                        "accuracy": round(t[4], 3) if t[4] else None,
                    }
                    for t in by_type
                ],
            },
            indent=1,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily suggestion manager")
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record")
    rec.add_argument("--capital", type=float, default=25_000.0)
    rec.add_argument("--risk-pct", type=float, default=1.0)

    sub.add_parser("settle")

    sub.add_parser("report")

    args = parser.parse_args()
    settings = load_settings()

    if args.command == "record":
        return cmd_record(settings, capital=args.capital, risk_pct=args.risk_pct)
    elif args.command == "settle":
        return cmd_settle(settings)
    elif args.command == "report":
        return cmd_report(settings)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
