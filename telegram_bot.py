import json
import urllib.parse
import urllib.request

import config


def send_telegram_message(message):
    """
    Sends a message to the pre-configured Telegram chat.
    Uses native urllib.request to avoid external dependency requirements (e.g., requests).
    """
    if (
        not config.TELEGRAM_ENABLED
        or not config.TELEGRAM_TOKEN
        or not config.TELEGRAM_CHAT_ID
    ):
        return False

    url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
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
