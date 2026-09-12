#!/usr/bin/env python3
"""
EQATS Multi-Channel Webhook Alert Dispatcher
Sends real-time notification alerts to Telegram / Slack / Discord on key events:
- Integration milestone completion (every N repos)
- Circuit breaker / draw-down triggers
- Workflow cascade progress reports
"""

import json
import os
import urllib.request
from typing import Any, Dict


def send_webhook_alert(event_type: str, title: str, message: str) -> dict[str, Any]:
    """
    Dispatches alerts to configured webhook endpoints (Slack, Telegram, Discord).
    Reads SLACK_WEBHOOK_URL, TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID, or DISCORD_WEBHOOK_URL.
    """
    dispatched = []

    # 1. Slack Webhook Dispatch
    slack_url = os.getenv("SLACK_WEBHOOK_URL")
    if slack_url:
        try:
            payload = json.dumps({
                "text": f"*:rocket: [{event_type}] {title}*\n{message}"
            }).encode("utf-8")
            req = urllib.request.Request(slack_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5):
                dispatched.append("SLACK")
        except Exception as err:
            print(f"[-] Slack alert failed: {err}")

    # 2. Discord Webhook Dispatch
    discord_url = os.getenv("DISCORD_WEBHOOK_URL")
    if discord_url:
        try:
            payload = json.dumps({
                "content": f"**[{event_type}] {title}**\n{message}"
            }).encode("utf-8")
            req = urllib.request.Request(discord_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5):
                dispatched.append("DISCORD")
        except Exception as err:
            print(f"[-] Discord alert failed: {err}")

    # 3. Telegram Bot Dispatch
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat = os.getenv("TELEGRAM_CHAT_ID")
    if telegram_token and telegram_chat:
        try:
            telegram_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
            payload = json.dumps({
                "chat_id": telegram_chat,
                "text": f"[{event_type}] {title}\n{message}",
                "parse_mode": "Markdown"
            }).encode("utf-8")
            req = urllib.request.Request(telegram_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5):
                dispatched.append("TELEGRAM")
        except Exception as err:
            print(f"[-] Telegram alert failed: {err}")

    return {
        "event_type": event_type,
        "title": title,
        "dispatched_channels": dispatched,
    }


if __name__ == "__main__":
    import sys
    event = sys.argv[1] if len(sys.argv) > 1 else "MILESTONE"
    title_arg = sys.argv[2] if len(sys.argv) > 2 else "Integration Progress Update"
    msg_arg = sys.argv[3] if len(sys.argv) > 3 else "EQATS Autonomous Integration Engine is executing active batch cycles."

    res = send_webhook_alert(event, title_arg, msg_arg)
    print(f"[+] Alert Dispatcher Result: {res}")
