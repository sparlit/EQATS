import urllib.request
import urllib.parse
import json
import config

def send_telegram_message(message):
    """
    Sends a message to the pre-configured Telegram chat.
    Uses native urllib.request to avoid external dependency requirements (e.g., requests).
    """
    if not getattr(config, 'TELEGRAM_ENABLED', False) or not getattr(config, 'TELEGRAM_TOKEN', '') or not getattr(config, 'TELEGRAM_CHAT_ID', ''):
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=5) as response:
            res_data = response.read()
            res_json = json.loads(res_data.decode("utf-8"))
            return res_json.get("ok", False)
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")
        return False


def send_discord_webhook_message(message, title="EAQTS Execution Alert"):
    """
    Broadcasts execution telemetry and daily equity audits to a Discord webhook channel.
    Uses native urllib.request for dependency-free HTTPS execution.
    """
    if not getattr(config, 'DISCORD_WEBHOOK_ENABLED', False) or not getattr(config, 'DISCORD_WEBHOOK_URL', ''):
        return False

    webhook_url = config.DISCORD_WEBHOOK_URL
    payload = {
        "username": "EAQTS Autonomous Trader",
        "embeds": [
            {
                "title": title,
                "description": message,
                "color": 3066993, # Neon Cyan / Blue
                "footer": {"text": "Elite Autonomous Quantum Trading System v5.0"}
            }
        ]
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "EAQTS-Webhook/5.0"}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status in (200, 204)
    except Exception as e:
        print(f"Failed to send Discord webhook message: {e}")
        return False


def broadcast_execution_alert(message, title="EAQTS Order Alert"):
    """
    Unified broadcast function dispatching alerts across both Telegram and Discord channels.
    """
    telegram_res = send_telegram_message(f"*{title}*\n{message}")
    discord_res = send_discord_webhook_message(message, title=title)
    return telegram_res or discord_res
