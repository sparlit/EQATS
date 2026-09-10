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


#!/usr/bin/env python3
"""
send_digest.py
Telegram digest of the latest scan. Implements the C3 plan item.

Behaviour:
  - Reads latest_scan.json + history_index.json.
  - Composes a compact markdown message: regime, PASS count, top-5 by
    score, watchlist-name triggers when applicable.
  - POSTs to the Telegram Bot API. Fails soft (exit 0) when secrets are
    missing or Telegram returns non-2xx — the scan is the load-bearing
    artifact and an alert outage must never block it.

Required environment variables:
  TELEGRAM_BOT_TOKEN    Bot token from @BotFather
  TELEGRAM_CHAT_ID      Target chat (numeric ID or @channel)

Usage:
    python backend/scripts/send_digest.py \\
        --latest ../frontend/public/data/latest_scan.json \\
        --history ../frontend/public/data/snapshots/history_index.json

Exit codes:
  0  success OR skipped (no secrets / no data) OR Telegram error (logged)
  1  invalid arguments / unreadable inputs
"""
import argparse
import contextlib
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

# Cap the message body to stay under Telegram's 4096-char limit with margin.
MAX_MESSAGE_LEN = 3500


def _safe(v, default: str = "—") -> str:
    return default if v is None else str(v)


def _fmt_pct(v) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def _fmt_rupees(v) -> str:
    if v is None:
        return "—"
    try:
        return f"₹{float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _regime_label(idx_pct) -> tuple:
    if idx_pct is None:
        return ("(unknown)", "")
    if idx_pct > 2:
        return ("Nifty > 200EMA", "🟢")
    if idx_pct < -2:
        return ("Below 200EMA — be selective", "🔴")
    return ("Near 200EMA", "🟡")


def build_message(latest_path: str, history_path: str | None) -> str | None:
    if not os.path.exists(latest_path):
        return None
    try:
        with open(latest_path) as f:
            scan = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    stocks = scan.get("stocks", [])
    passed = [s for s in stocks if s.get("gate_pass")]
    top = sorted(passed, key=lambda s: (s.get("swing_score") is None, -(s.get("swing_score") or 0)))[:5]

    # Index regime: pick from first row that has it (universe-constant).
    idx_pct = None
    for s in stocks:
        if isinstance(s.get("market_index_pct_from_ema200"), (int, float)):
            idx_pct = s["market_index_pct_from_ema200"]
            break
    regime_label, regime_emoji = _regime_label(idx_pct)

    gate_pass = scan.get("gate_pass_count", len(passed))
    universe = scan.get("universe_size", len(stocks))

    lines = []
    lines.append(f"*NSE Swing Scanner* — {scan.get('generated_at', '')[:16].replace('T', ' ')} UTC")
    lines.append(f"{regime_emoji} Regime: *{regime_label}* ({_fmt_pct(idx_pct)})")
    lines.append(f"PASS: *{gate_pass} / {universe}*")
    cov = scan.get("coverage") or {}
    if cov:
        priced = cov.get("priced")
        univ = cov.get("universe", universe)
        pct = cov.get("pct")
        rl = cov.get("rate_limited") or 0
        pct_s = f"{pct * 100:.0f}%" if isinstance(pct, (int, float)) else "—"
        lines.append(f"Coverage: *{priced}/{univ}* priced ({pct_s})" + (f", {rl} rate-limited" if rl else ""))
    lines.append("")

    if top:
        lines.append("*Top 5 by score*")
        for s in top:
            sym = s.get("symbol")
            sc = s.get("swing_score")
            rsi = s.get("rsi14")
            px = _fmt_rupees(s.get("current_price"))
            t1 = _fmt_rupees(s.get("target_1"))
            stop = _fmt_rupees(s.get("stop_loss"))
            lines.append(f"• `{sym}` score *{_safe(sc)}* · px {px} · RSI {_safe(rsi)} · T1 {t1} · stop {stop}")
    else:
        lines.append("_No names passed the gates today._")

    # Stale-source warnings (count, not per-symbol — keep message short).
    bad_sources: dict = {}
    for s in stocks:
        for k in (
            "delivery_source_status",
            "surveillance_source_status",
            "holdings_source_status",
            "corporate_actions_status",
        ):
            v = s.get(k)
            if v in ("source_failed", "flag_only"):
                bad_sources[k] = bad_sources.get(k, 0) + 1
    if bad_sources:
        lines.append("")
        lines.append("*Source warnings*")
        for k, n in sorted(bad_sources.items()):
            pretty = k.replace("_source_status", "").replace("_", " ").title()
            lines.append(f"• {pretty}: {n} row(s) `{k}`")

    msg = "\n".join(lines)
    if len(msg) > MAX_MESSAGE_LEN:
        msg = msg[: MAX_MESSAGE_LEN - 50] + "\n…_(truncated)_"
    return msg


def send_telegram(message: str) -> tuple:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return (False, "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; skipping digest.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return (True, f"Telegram HTTP {resp.status}; body[:120]={body[:120]}")
    except urllib.error.HTTPError as e:
        body = ""
        with contextlib.suppress(Exception):
            body = e.read().decode("utf-8", errors="replace")[:200]
        return (False, f"Telegram HTTPError {e.code}: {body}")
    except urllib.error.URLError as e:
        return (False, f"Telegram URLError: {e.reason}")
    except Exception as e:
        return (False, f"Telegram send failed: {e}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Send a Telegram digest of the latest scan.")
    p.add_argument("--latest", required=True, help="Path to latest_scan.json")
    p.add_argument("--history", default=None, help="Path to history_index.json (reserved)")
    args = p.parse_args(argv)

    message = build_message(args.latest, args.history)
    if not message:
        print("::notice::send_digest: no scan data available; skipping.")
        return 0

    ok, info = send_telegram(message)
    if ok:
        print(f"send_digest: sent ({len(message)} chars). {info}")
        return 0
    # Always soft-fail — the scan is the load-bearing artifact.
    print(f"::warning::send_digest: {info}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
