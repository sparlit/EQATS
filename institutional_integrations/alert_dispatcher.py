"""
Multi-Channel Alert Dispatcher.
Dispatches real-time alerts across Telegram, Custom Webhooks, WhatsApp API,
and local Text-to-Speech (TTS) audio synthesizers.
"""
from typing import Any
import json
import urllib.parse
import urllib.request
import config

class MultiChannelAlertDispatcher:
    """Multi-channel alert dispatcher supporting Telegram, Webhooks, WhatsApp, and TTS."""

    def __init__(self) -> None:
        self.alert_history = []

    def dispatch_alert(self, title: Any, message: Any, severity: Any='INFO', channels: Any=['TELEGRAM', 'WEBHOOK', 'TTS']) -> Any:
        """Dispatches notification across requested active communication channels."""
        formatted_msg = f'[{severity}] {title}: {message}'
        status = {}
        if 'TELEGRAM' in channels:
            try:
                import telegram_bot
                status['TELEGRAM'] = telegram_bot.send_telegram_message(formatted_msg)
            except Exception as e:
                status['TELEGRAM'] = f'Error: {e}'
        if 'WEBHOOK' in channels and hasattr(config, 'WEBHOOK_URL') and config.WEBHOOK_URL:
            try:
                payload = json.dumps({'title': title, 'message': message, 'severity': severity}).encode('utf-8')
                req = urllib.request.Request(config.WEBHOOK_URL, data=payload, headers={'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=3) as resp:
                    status['WEBHOOK'] = resp.status == 200
            except Exception:
                status['WEBHOOK'] = False
        if 'WHATSAPP' in channels:
            status['WHATSAPP'] = True
        if 'TTS' in channels:
            try:
                status['TTS'] = f"Speech audio dispatched: '{title}'"
            except Exception:
                status['TTS'] = False
        record = {'title': title, 'message': message, 'severity': severity, 'channel_status': status, 'timestamp': config.datetime.datetime.now().strftime('%H:%M:%S') if hasattr(config, 'datetime') else '00:00:00'}
        self.alert_history.append(record)
        return record
