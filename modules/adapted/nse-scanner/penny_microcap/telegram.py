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


"""Dedicated Telegram formatting and transport for the penny shadow system."""

import html
import os
import re
import time
from dataclasses import dataclass

import requests
from telegram_dashboard import dashboard_keyboard, status_label

ICONS = {"READY": "🟢", "CONFIRMING": "🟡", "EARLY_RADAR": "🔵", "CIRCUIT_LOCKED": "🔴", "EXTENDED": "🟠"}


@dataclass(frozen=True)
class DeliveryResult:
    sent: bool
    reason: str


def _link(symbol: str) -> str:
    safe = html.escape(symbol)
    return f'<a href="https://www.tradingview.com/chart/?symbol=NSE%3A{safe}">{safe}</a>'


def _card(row: dict) -> str:
    state, metrics = row["state"], row.get("metrics", {})
    lines = [
        "━━━━━━━━━━━━━━",
        f"{ICONS.get(state, '⚪')} <b>{_link(row['symbol'])} • {status_label(state)} • {row['score']:.0f}/100</b>",
        f"CMP ₹{row['close']:.2f}",
        f"Evidence: 5D {metrics.get('return_5d_pct', 0):+.1f}% • Turnover {metrics.get('turnover_ratio', 0):.1f}× normal",
    ]
    if row.get("entry_low") is not None:
        lines.append(f"Entry: ₹{row['entry_low']:.2f}–₹{row['entry_high']:.2f}")
    if metrics.get("liquidity_tier") == "HIGH":
        lines.append("Liquidity: <b>High</b>")
    if state == "CIRCUIT_LOCKED":
        lines.extend(["Current entry: <b>NOT EXECUTABLE</b>", "Next: Wait for normal two-way trading"])
    elif state == "EXTENDED":
        lines.extend([f"Distance {metrics.get('distance_atr', 0):.1f} ATR", "Next: Do not chase; wait for reset"])
    elif state == "READY":
        lines.extend(
            [
                f"Planned SL ₹{row['stop']:.2f} • T1 ₹{row['target1']:.2f} • T2 ₹{row['target2']:.2f}",
                "Next: The simulator adds this only if the next-session entry rule is met.",
            ]
        )
    elif state == "CONFIRMING":
        lines.append("Next: Await executable closed-bar confirmation")
    else:
        lines.append("Next: Confirm sustained participation")
    return "\n".join(lines)


TOPIC_STATES = {
    "early_radar": {"EARLY_RADAR"},
    "confirming": {"CONFIRMING"},
    "ready": {"READY"},
    "circuit_risk": {"CIRCUIT_LOCKED", "EXTENDED"},
}

TOPIC_TITLES = {
    "early_radar": "🔵 <b>PENNY — EARLY WATCHLIST</b>",
    "confirming": "🟡 <b>PENNY — WAIT FOR CONFIRMATION</b>",
    "ready": "🟢 <b>PENNY — WATCH FOR ENTRY</b>",
    "circuit_risk": "🚧 <b>PENNY CIRCUIT & RISK</b>",
}


def _header(report: dict, title: str) -> str:
    counts = report.get("counts", {})
    return "\n".join(
        [
            title,
            f"<b>{report.get('as_of_date', 'N/A')} EOD • SIMULATED WATCHLIST — NO LIVE ORDERS</b>",
            f"Universe {report.get('universe_symbols', 0)} • Selected {report.get('selected', 0)}",
            f"Watch for entry {counts.get('READY', 0)} • Waiting for confirmation {counts.get('CONFIRMING', 0)} • Early watchlist {counts.get('EARLY_RADAR', 0)}",
            "",
        ]
    )


def render_topic_messages(report: dict, topic: str, *, limit: int = 3400, cards_per_page: int = 7) -> list[str]:
    if topic == "portfolio":
        positions = report.get("portfolio", [])
        header = _header(report, "📂 <b>PENNY PORTFOLIO</b>")
        if not positions:
            return [
                header
                + "No simulated positions are open. Watchlist candidates remain watchlist items until the entry rule is met.\n\n⚠️ HIGH-RISK MICROCAP RESEARCH — NOT ADVICE"
            ]
        rows = positions
    elif topic == "system":
        counts = report.get("counts", {})
        return [
            "\n".join(
                [
                    "⚙️ <b>PENNY SCANNER SYSTEM</b>",
                    f"<b>{report.get('as_of_date', 'N/A')} EOD • HEALTHY</b>",
                    f"Data universe: {report.get('universe_symbols', 0)} symbols",
                    f"Qualified: {report.get('selected', 0)}",
                    f"Early watchlist {counts.get('EARLY_RADAR', 0)} • Waiting for confirmation {counts.get('CONFIRMING', 0)} • Watch for entry {counts.get('READY', 0)}",
                    f"Circuit risk {counts.get('CIRCUIT_LOCKED', 0)} • Wait for pullback {counts.get('EXTENDED', 0)}",
                    f"Strategy: {html.escape(str(report.get('strategy_version', 'N/A')))} • simulated research only",
                ]
            )
        ]
    elif topic in TOPIC_STATES:
        rows = [r for r in report.get("candidates", []) if r["state"] in TOPIC_STATES[topic]]
        header = _header(report, TOPIC_TITLES[topic])
    else:
        msg = f"Unknown Penny topic: {topic}"
        raise ValueError(msg)

    footer = "\n\n⚠️ HIGH-RISK MICROCAP RESEARCH — NOT ADVICE"
    pages, current, cards = [], header, 0
    if not rows:
        empty = (
            "No new circuit or extension risks."
            if topic == "circuit_risk"
            else "No qualifying candidates in this stage today."
        )
        return [header + empty + footer]
    for row in rows:
        card = _card(row)
        if cards and (cards >= cards_per_page or len(current) + len(card) + len(footer) + 2 > limit):
            pages.append(current + footer)
            current, cards = header, 0
        current += card + "\n"
        cards += 1
    pages.append(current.rstrip() + footer)
    return pages


def render_messages(report: dict, *, risk_only: bool = False, limit: int = 3400, cards_per_page: int = 7) -> list[str]:
    """Compatibility wrapper for callers using the original two-route API."""
    if risk_only:
        return render_topic_messages(report, "circuit_risk", limit=limit, cards_per_page=cards_per_page)
    pages = []
    for topic in ("ready", "confirming", "early_radar"):
        pages.extend(render_topic_messages(report, topic, limit=limit, cards_per_page=cards_per_page))
    return pages


def send_messages(messages: list[str], kind: str, *, enabled: bool, timeout: int = 20) -> DeliveryResult:
    if not enabled:
        return DeliveryResult(False, "disabled")
    token, chat_id = os.getenv("PENNY_TELEGRAM_BOT_TOKEN", "").strip(), os.getenv("PENNY_TELEGRAM_CHAT_ID", "").strip()
    topic_names = {
        "early_radar": "PENNY_TOPIC_EARLY_RADAR",
        "confirming": "PENNY_TOPIC_CONFIRMING",
        "ready": "PENNY_TOPIC_READY",
        "circuit_risk": "PENNY_TOPIC_CIRCUIT_RISK",
        "portfolio": "PENNY_TOPIC_PORTFOLIO",
        "system": "PENNY_TOPIC_SYSTEM",
    }
    topic = os.getenv(topic_names[kind], "").strip()
    if not token or not chat_id:
        return DeliveryResult(False, "credentials_not_configured")
    if not topic:
        return DeliveryResult(False, f"topic_not_configured:{kind}")
    for index, message in enumerate(messages, start=1):
        payload = {
            "chat_id": chat_id,
            "message_thread_id": int(topic),
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if index == len(messages) and kind != "system":
            payload["reply_markup"] = dashboard_keyboard("penny")
        try:
            response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=timeout)
            if getattr(response, "status_code", 200) == 400:
                payload.pop("parse_mode", None)
                payload["text"] = html.unescape(re.sub(r"<[^>]+>", "", message))
                response = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=timeout
                )
            response.raise_for_status()
        except (requests.RequestException, ValueError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return DeliveryResult(False, f"page_{index}:telegram_http_{status or 'network'}:{type(exc).__name__}")
        if index < len(messages):
            time.sleep(0.15)
    return DeliveryResult(True, "sent")
