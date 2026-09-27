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


"""Generate the friction-leakage HTML dashboard for a backtest run.

Usage:
    python scripts/friction_report.py                # latest run
    python scripts/friction_report.py --run-id sma-xxxx-yyyy
"""


import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
from indian_quant.config import load_settings
from indian_quant.research.friction import compute_friction_metrics

TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Friction report · {run_id}</title>
<style>
body{{background:#0a0e14;color:#dbe7ff;font-family:ui-monospace,Menlo,Consolas,monospace;margin:0;padding:40px}}
h1{{font-size:20px;color:#00e5a0}} .sub{{color:#7d90b5;font-size:12px;margin-bottom:28px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;max-width:980px}}
.card{{background:#111a2b;border:1px solid #1c2a42;border-radius:12px;padding:18px 20px}}
.card .k{{color:#4a5d80;font-size:10.5px;letter-spacing:1.2px;text-transform:uppercase}}
.card .v{{font-size:24px;margin-top:6px}} .good{{color:#00e5a0}} .bad{{color:#ff6b81}} .warn{{color:#ffb454}}
.bar-wrap{{margin-top:8px;background:#0a0e14;border-radius:6px;height:10px;width:100%;overflow:hidden}}
.bar{{height:100%;border-radius:6px}}
table{{border-collapse:collapse;margin-top:26px;max-width:980px;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid #1c2a42;padding:7px 12px;text-align:left}} th{{color:#4a5d80;font-weight:400;text-transform:uppercase;font-size:10px;letter-spacing:1px}}
</style></head><body>
<h1>&gt;_ frictional leakage · {run_id}</h1>
<div class="sub">{instrument} · generated {generated}</div>
<div class="grid">
  <div class="card"><div class="k">gross pnl</div><div class="v {gross_cls}">{gross_pnl}</div></div>
  <div class="card"><div class="k">total commissions</div><div class="v warn">{total_commissions}</div></div>
  <div class="card"><div class="k">alpha leakage</div><div class="v {leak_cls}">{alpha_leakage}</div>
    <div class="bar-wrap"><div class="bar" style="width:{leak_bar}%;background:{leak_color}"></div></div></div>
  <div class="card"><div class="k">realized cost</div><div class="v">{realized_cost_bps} bps</div>
    <div style="color:#4a5d80;font-size:10px">of traded notional</div></div>
</div>
<table><tr><th>metric</th><th>value</th></tr>{rows}</table>
<div style="margin-top:26px" class="sub">commissions by side — STT makes sells structurally dearer:</div>
<table>
<tr><th>side</th><th>commissions</th><th></th></tr>
<tr><td>BUY</td><td>₹{commissions_buy}</td><td><div class="bar-wrap" style="width:320px"><div class="bar" style="width:{buy_pct}%;background:#4da3ff"></div></div></td></tr>
<tr><td>SELL</td><td>₹{commissions_sell}</td><td><div class="bar-wrap" style="width:320px"><div class="bar" style="width:{sell_pct}%;background:#ffb454"></div></div></td></tr>
</table>
</body></html>"""


def load_run(settings, run_id: str | None):
    base = settings.data_root / "normalized" / "backtests"
    if run_id is None:
        candidates = sorted(base.glob("*"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            msg = "no persisted backtest runs found"
            raise FileNotFoundError(msg)
        run_dir = candidates[-1]
    else:
        run_dir = base / run_id
    fills = pd.read_parquet(run_dir / "fills.parquet")
    positions_path = run_dir / "positions.parquet"
    positions = pd.read_parquet(positions_path) if positions_path.exists() else None
    return run_dir.name, fills, positions


def build_dashboard(metrics: dict, run_id: str, instrument: str) -> str:
    leak = metrics.get("alpha_leakage_pct")
    leak_val = f"{leak:.1f}%" if isinstance(leak, (int, float)) else "n/a"
    if isinstance(leak, (int, float)) and leak > 100:
        leak_cls, leak_color, leak_bar = "bad", "#ff6b81", 100
    elif isinstance(leak, (int, float)):
        leak_cls, leak_color, leak_bar = "warn", "#ffb454", max(2, min(100, leak))
    else:
        leak_cls, leak_color, leak_bar = "", "#1c2a42", 2

    gross = metrics.get("gross_pnl")
    gross_cls = (
        "good"
        if isinstance(gross, (int, float)) and gross > 0
        else ("bad" if isinstance(gross, (int, float)) and gross < 0 else "")
    )
    buy = float(metrics.get("commissions_buy") or 0)
    sell = float(metrics.get("commissions_sell") or 0)
    denom = max(buy + sell, 1e-9)

    rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>"
        for k, v in metrics.items()
        if k
        not in (
            "gross_pnl",
            "total_commissions",
            "alpha_leakage_pct",
            "realized_cost_bps",
            "commissions_buy",
            "commissions_sell",
        )
    )
    from datetime import UTC, datetime

    return TEMPLATE.format(
        run_id=run_id,
        instrument=instrument,
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        gross_pnl=f"₹{metrics.get('gross_pnl')}",
        total_commissions=f"₹{metrics.get('total_commissions')}",
        alpha_leakage=leak_val,
        realized_cost_bps=metrics.get("realized_cost_bps") or "n/a",
        gross_cls=gross_cls,
        leak_cls=leak_cls,
        leak_color=leak_color,
        leak_bar=leak_bar,
        commissions_buy=f"{buy:,.2f}",
        commissions_sell=f"{sell:,.2f}",
        buy_pct=max(2, buy / denom * 100),
        sell_pct=max(2, sell / denom * 100),
        rows=rows,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Friction leakage dashboard")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    settings = load_settings(args.config)
    run_id, fills, positions = load_run(settings, args.run_id)
    instrument = str(fills["instrument_id"].iloc[0]) if "instrument_id" in fills.columns and len(fills) else "n/a"
    bt_cfg = settings.backtest
    metrics = compute_friction_metrics(fills, positions, starting_balance=bt_cfg.starting_balance_inr)
    print(json.dumps(metrics, indent=2))

    out_dir = Path("dashboards")
    out_dir.mkdir(exist_ok=True)
    html = build_dashboard(metrics, run_id, instrument)
    out_path = out_dir / f"friction_{run_id}.html"
    out_path.write_text(html)
    print(f"dashboard -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
