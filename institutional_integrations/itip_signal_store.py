"""
ITIP Multi-Timeframe Signal Store & Persistence Subsystem.
Provides thread-safe logging and retrieval for multi-timeframe trading signals.
"""
import json
import os
import threading
from typing import Any, Dict, List
LOG_DIR = './logs'
CSV_PATH = os.path.join(LOG_DIR, 'signals_log.csv')
JSON_PATH = os.path.join(LOG_DIR, 'signals_log.json')
_store_lock = threading.Lock()
SIGNAL_FIELDS = ('timestamp', 'symbol', 'timeframe', 'direction', 'confidence', 'session', 'atr', 'rsi')

def init_store() -> None:
    """Creates the log directory and the CSV header when missing."""
    os.makedirs(LOG_DIR, exist_ok=True)
    with _store_lock:
        if not os.path.exists(CSV_PATH):
            with open(CSV_PATH, 'w', encoding='utf-8') as f:
                f.write(','.join(SIGNAL_FIELDS) + '\n')

def read_signals() -> List[Dict[str, Any]]:
    """Returns all logged signals, or an empty list if missing/corrupt."""
    if not os.path.exists(JSON_PATH):
        return []
    with _store_lock:
        try:
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

def append_signal(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Appends a signal to both CSV and JSON logs in a thread-safe manner."""
    init_store()
    record = {field: signal.get(field, '') for field in SIGNAL_FIELDS}
    with _store_lock:
        try:
            with open(CSV_PATH, 'a', encoding='utf-8') as f:
                f.write(','.join((str(record[field]) for field in SIGNAL_FIELDS)) + '\n')
            signals = []
            if os.path.exists(JSON_PATH):
                try:
                    with open(JSON_PATH, 'r', encoding='utf-8') as f:
                        signals = json.load(f)
                except Exception:
                    signals = []
            signals.append(record)
            with open(JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(signals, f, indent=4)
        except Exception:
            pass
    return record
