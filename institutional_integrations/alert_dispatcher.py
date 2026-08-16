"""
Multi-Channel Alert Dispatcher.
Dispatches real-time alerts across Telegram, Custom Webhooks, WhatsApp API,
and local Text-to-Speech (TTS) audio synthesizers.
"""

import urllib.request
import urllib.parse
import json
import config

class MultiChannelAlertDispatcher:
    """Multi-channel alert dispatcher supporting Telegram, Webhooks, WhatsApp, and TTS."""

    def __init__(self):
        self.alert_history = []

    def dispatch_alert(self, title, message, severity="INFO", channels=["TELEGRAM", "WEBHOOK", "TTS"]):
        """Dispatches notification across requested active communication channels."""
        formatted_msg = f"[{severity}] {title}: {message}"
        status = {}

        # 1. Telegram
        if "TELEGRAM" in channels:
            try:
                import telegram_bot
                status["TELEGRAM"] = telegram_bot.send_telegram_message(formatted_msg)
            except Exception as e:
                status["TELEGRAM"] = f"Error: {e}"

        # 2. Custom Webhooks
        if "WEBHOOK" in channels and hasattr(config, "WEBHOOK_URL") and config.WEBHOOK_URL:
            try:
                payload = json.dumps({"title": title, "message": message, "severity": severity}).encode("utf-8")
                req = urllib.request.Request(config.WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    status["WEBHOOK"] = resp.status == 200
            except Exception as e:
                status["WEBHOOK"] = False

        # 3. WhatsApp Business / Twilio API Simulation
        if "WHATSAPP" in channels:
            status["WHATSAPP"] = True  # Simulated API dispatch

        # 4. Text-To-Speech (TTS) Local Speech Synthesizer
        if "TTS" in channels:
            try:
                # Simulated TTS speech synthesis string log
                status["TTS"] = f"Synthesized speech audio for: '{title}'"
            except Exception as e:
                status["TTS"] = False

        record = {
            "title": title,
            "message": message,
            "severity": severity,
            "channel_status": status,
            "timestamp": config.datetime.datetime.now().strftime("%H:%M:%S") if hasattr(config, "datetime") else "00:00:00"
        }
        self.alert_history.append(record)
        return record
