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


"""Read-only data loading for web dashboard. No mutations."""


import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import sqlalchemy as sa


def _sanitize(obj):
    """Convert numpy/pandas types to plain Python for safe Jinja2 rendering."""
    return json.loads(json.dumps(obj, default=str))


def _settings():
    from indian_quant.config import load_settings

    return load_settings()


def _pg_engine():
    from indian_quant.config.connections import get_engine

    return get_engine()


def get_paper_summary() -> dict[str, Any]:
    engine = _pg_engine()
    with engine.connect() as conn:
        settled = conn.execute(
            sa.text("""
            SELECT COUNT(*), AVG(realized_net_bps),
                   SUM(CASE WHEN realized_net_bps > 0 THEN 1 ELSE 0 END)*1.0/COUNT(*)
            FROM paper_signals WHERE status='SETTLED'
        """)
        ).fetchone()
        open_n = conn.execute(sa.text("SELECT COUNT(*) FROM paper_signals WHERE status='OPEN'")).fetchone()[0]
        cursor = conn.execute(sa.text("SELECT * FROM paper_signals WHERE status='OPEN' ORDER BY created_at DESC"))
        cols = cursor.keys()
        open_rows = []
        for row in cursor.fetchall():
            entry = {}
            for col, val in zip(cols, row, strict=False):
                if isinstance(val, bytes):
                    val = val.decode()
                elif not isinstance(val, (int, float, str, bool, type(None))):
                    val = str(val)
                entry[col] = val
            open_rows.append(entry)
    result = {
        "open": int(open_n),
        "settled": int(settled[0]) if settled[0] else 0,
        "avg_net_bps": float(round(settled[1], 1)) if settled[1] is not None else None,
        "hit_rate": float(round(settled[2], 3)) if settled[2] is not None else None,
        "open_positions": open_rows,
    }
    # Add by_horizon breakdown
    with engine.connect() as conn:
        hz_rows = conn.execute(
            sa.text("""
            SELECT horizon_label as label,
                   COUNT(*) as total,
                   SUM(CASE WHEN status='SETTLED' THEN 1 ELSE 0 END) as settled,
                   SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) as open_n,
                   AVG(CASE WHEN status='SETTLED' THEN realized_net_bps END) as avg_net_bps,
                   AVG(CASE WHEN status='SETTLED' AND realized_net_bps > 0 THEN 1.0 ELSE 0.0 END) as hit_rate
            FROM paper_signals
            WHERE horizon_label IS NOT NULL
            GROUP BY horizon_label
            ORDER BY horizon_label
        """)
        ).fetchall()
        result["by_horizon"] = [
            {
                "label": r[0],
                "total": int(r[1] or 0),
                "settled": int(r[2] or 0),
                "open": int(r[3] or 0),
                "avg_net_bps": round(float(r[4]), 1) if r[4] is not None else None,
                "hit_rate": round(float(r[5]), 3) if r[5] is not None else None,
            }
            for r in hz_rows
        ]
    return _sanitize(result)


def get_gate_progress() -> dict[str, Any]:
    s = get_paper_summary()
    target = 20
    floor_bps = 25.0
    pct = min(100, int(s["settled"] / target * 100)) if s["settled"] else 0
    net_ok = s["avg_net_bps"] is not None and s["avg_net_bps"] >= floor_bps
    passed = s["settled"] >= target and net_ok
    result = {
        "target": int(target),
        "settled": int(s["settled"]),
        "pct": int(pct),
        "avg_net_bps": s["avg_net_bps"],
        "floor_bps": float(floor_bps),
        "net_ok": bool(net_ok),
        "passed": bool(passed),
    }
    return _sanitize(result)


def get_latest_signals() -> dict[str, Any]:
    dl_dir = _settings().normalized_dir / "delivery" / "NSE"
    rows: list[dict[str, Any]] = []
    latest_date = ""
    for path in sorted(dl_dir.glob("*.parquet")):
        try:
            raw = pd.read_parquet(path, columns=["date", "symbol", "segment", "close", "deliv_pct", "volume"])
        except Exception:
            continue
        if raw.empty or len(raw) < 20:
            continue
        frame = raw.copy()
        frame["date_str"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
        d = frame["date_str"].iloc[-1]
        latest_date = max(latest_date, d)
        last = frame.iloc[-1]
        prev = frame.iloc[-2] if len(frame) > 1 else frame.iloc[-1]
        deliv_series = pd.to_numeric(frame["deliv_pct"], errors="coerce").dropna()
        if len(deliv_series) < 15:
            continue
        mean = deliv_series.tail(30).mean()
        std = deliv_series.tail(30).std()
        z = (last["deliv_pct"] - mean) / std if std > 0 else np.nan
        ret = (float(last["close"]) / float(prev["close"]) - 1.0) if float(prev["close"]) > 0 else 0.0
        rows.append(
            {
                "symbol": str(last["symbol"]),
                "segment": str(last["segment"]) if "segment" in frame.columns else "EQ",
                "close": round(float(last["close"]), 2),
                "deliv_pct": round(float(last["deliv_pct"]), 1) if not pd.isna(last["deliv_pct"]) else None,
                "deliv_z": round(float(z), 2) if not pd.isna(z) else None,
                "ret_1d_pct": round(ret * 100, 2),
                "_date": d,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return {"date": "", "buys": [], "avoids": [], "total_scanned": 0}
    today = df[df["_date"] == latest_date].copy()
    buys = today[(today["deliv_z"] >= 2) & (today["ret_1d_pct"] >= 0.5)]
    avoids = today[(today["deliv_z"] >= 2) & (today["ret_1d_pct"] <= -0.5)]
    buys = buys.sort_values("deliv_z", ascending=False)
    avoids = avoids.sort_values("deliv_z", ascending=False)

    result = {
        "date": str(latest_date),
        "buys": buys.replace(np.nan, None).to_dict(orient="records"),
        "avoids": avoids.replace(np.nan, None).to_dict(orient="records"),
        "total_scanned": len(today),
    }
    return _sanitize(result)


def get_research_results() -> dict[str, Any]:
    gen_dir = Path("docs/research/generated")
    out: dict[str, Any] = {}
    for name in (
        "delivery_sweep.json",
        "delivery_r2b.json",
        "event_type_car.json",
        "deflation_verdict.json",
        "sme_dz_hi_up_5d.json",
        "entry_analysis.json",
    ):
        path = gen_dir / name
        if path.exists():
            key = name.replace(".json", "")
            out[key] = _sanitize(json.loads(path.read_text()))
    return out


def get_announcements(symbol: str) -> list[dict[str, Any]]:
    path = _settings().normalized_dir / "announcements" / "NSE" / f"{symbol}.parquet"
    if not path.exists():
        return []
    df = pd.read_parquet(path)
    return _sanitize(df.tail(20).replace(np.nan, None).to_dict(orient="records"))


def get_available_announcement_symbols() -> list[str]:
    dl_dir = _settings().normalized_dir / "announcements" / "NSE"
    if not dl_dir.exists():
        return []
    return sorted(p.stem for p in dl_dir.glob("*.parquet"))
