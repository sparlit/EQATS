"""
AXIOM Telegram Bot — send alerts via Telegram Bot API.
Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env.
Get a token: message @BotFather on Telegram → /newbot
Get your chat ID: message @userinfobot on Telegram
"""
from __future__ import annotations

import os

import requests
from dotenv import load_dotenv
from loguru import logger

_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_TIMEOUT  = 10


def _token() -> str | None:
    load_dotenv(override=True)
    return os.getenv("TELEGRAM_BOT_TOKEN")


def _chat_id() -> str | None:
    load_dotenv(override=True)
    return os.getenv("TELEGRAM_CHAT_ID")


def is_configured() -> bool:
    """Return True if both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set."""
    return bool(_token() and _chat_id())


def send_message(text: str, parse_mode: str = "HTML") -> tuple[bool, str]:
    """
    Send a plain text or HTML message to the configured chat.
    Returns (success, error_message).
    """
    if not is_configured():
        msg = "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env"
        logger.warning(msg)
        return False, msg
    url = _API_BASE.format(token=_token(), method="sendMessage")
    payload = {
        "chat_id": _chat_id(),
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=_TIMEOUT)
        if r.status_code == 200:
            return True, ""
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        api_desc = body.get("description", r.text[:300])
        logger.error("Telegram API error {}: {}", r.status_code, api_desc)
        return False, f"HTTP {r.status_code}: {api_desc}"
    except Exception as exc:
        logger.error("Telegram send failed: {}", exc)
        return False, str(exc)


def send_document(file_path, caption: str = "", parse_mode: str = "HTML") -> tuple[bool, str]:
    """
    Upload a file (e.g. the briefing PDF) to the configured chat via sendDocument.
    Returns (success, error_message).
    """
    from pathlib import Path

    if not is_configured():
        return False, "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"
    p = Path(file_path)
    if not p.exists():
        return False, f"file not found: {p}"

    url = _API_BASE.format(token=_token(), method="sendDocument")
    data = {"chat_id": _chat_id(), "caption": caption[:1024], "parse_mode": parse_mode}
    try:
        with open(p, "rb") as fh:
            files = {"document": (p.name, fh, "application/pdf")}
            r = requests.post(url, data=data, files=files, timeout=60)
        if r.status_code == 200:
            logger.success("Telegram document sent: {}", p.name)
            return True, ""
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        desc = body.get("description", r.text[:300])
        logger.error("Telegram sendDocument error {}: {}", r.status_code, desc)
        return False, f"HTTP {r.status_code}: {desc}"
    except Exception as exc:
        logger.error("Telegram sendDocument failed: {}", exc)
        return False, str(exc)


def send_alert(symbol: str, signal: str, price: float, details: str) -> bool:
    """Send a formatted trading alert."""
    emoji = {"BREAKOUT": "🚀", "BB_SQUEEZE_SETUP": "⚡", "MOMENTUM_CONT": "📈"}.get(signal, "🔔")
    text = (
        f"{emoji} <b>AXIOM ALERT — {symbol}</b>\n"
        f"Signal: <b>{signal}</b>\n"
        f"Price: ₹{price:,.2f}\n"
        f"{details}"
    )
    ok, _ = send_message(text)
    return ok


def send_regime_alert(regime: str, nifty_close: float, adx: float) -> bool:
    """Send a regime change alert."""
    emoji = {"BULLISH": "🟢", "NEUTRAL": "🟡", "BEARISH": "🔴"}.get(regime, "⚪")
    text = (
        f"{emoji} <b>AXIOM — REGIME: {regime}</b>\n"
        f"Nifty 50: ₹{nifty_close:,.2f}\n"
        f"ADX: {adx:.1f}"
    )
    ok, _ = send_message(text)
    return ok


def send_briefing(briefing_text: str, date_str: str) -> bool:
    """Send morning briefing summary (first 3000 chars)."""
    header = f"📊 <b>AXIOM Morning Briefing — {date_str}</b>\n\n"
    body = briefing_text[:3000]
    ok, _ = send_message(header + body)
    return ok


def send_test_message() -> tuple[bool, str]:
    """Send a test ping. Returns (success, error_message)."""
    return send_message("✅ <b>AXIOM</b> — Telegram connected successfully.")


def get_bot_info() -> tuple[dict, str]:
    """Call getMe to verify the token and return bot info."""
    token = _token()
    if not token:
        return {}, "TELEGRAM_BOT_TOKEN not set in .env"
    url = _API_BASE.format(token=token, method="getMe")
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        data = r.json()
        if data.get("ok"):
            return data.get("result", {}), ""
        return {}, data.get("description", f"HTTP {r.status_code}")
    except Exception as exc:
        return {}, str(exc)


def delete_webhook() -> tuple[bool, str]:
    """Delete any existing webhook so getUpdates can work."""
    token = _token()
    if not token:
        return False, "TELEGRAM_BOT_TOKEN not set in .env"
    url = _API_BASE.format(token=token, method="deleteWebhook")
    try:
        r = requests.get(url, timeout=_TIMEOUT)
        data = r.json()
        if data.get("ok"):
            return True, ""
        return False, data.get("description", "Unknown error")
    except Exception as exc:
        return False, str(exc)


def get_updates_chat_id() -> tuple[str | None, str, list]:
    """
    Call getUpdates to find the chat ID.
    Returns (chat_id, error_message, raw_results).
    """
    token = _token()
    if not token:
        return None, "TELEGRAM_BOT_TOKEN not set in .env", []
    url = _API_BASE.format(token=token, method="getUpdates")
    try:
        r = requests.get(url, params={"limit": 10, "timeout": 0}, timeout=_TIMEOUT)
        data = r.json()
        if not data.get("ok"):
            return None, data.get("description", f"HTTP {r.status_code}"), []
        results = data.get("result", [])
        if not results:
            return None, "No messages found — see instructions below.", []
        chat_id = str(results[-1]["message"]["chat"]["id"])
        return chat_id, "", results
    except Exception as exc:
        return None, str(exc), []
