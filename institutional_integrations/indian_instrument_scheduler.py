import database
'\nIndian Stock Exchange Instrument Token Daily Scheduler Module (EQATS Institutional Integration).\n\nDownloads Zerodha Kite Connect / Dhan master CSV/JSON instrument lists every day at\n08:45 AM India Standard Time (IST). Maintains a thread-safe bi-directional mapping dictionary\nthat translates human-readable string symbol keys (e.g., "NSE:SBIN", "NSE:RELIANCE", "NFO:NIFTY24MARFUT")\ninto the broker\'s active numeric token ID for the session.\n'
import csv
import io
import json
import logging
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple
_log = logging.getLogger('IndianInstrumentScheduler')
IST_TIMEZONE = timezone(timedelta(hours=5, minutes=30))

class IndianInstrumentScheduler:
    """
    Daily Master Instrument List Download & Token Translation Engine.
    """
    KITE_INSTRUMENTS_URL = 'https://api.kite.trade/instruments'
    DHAN_INSTRUMENTS_URL = 'https://images.dhan.co/api-data/api-scrip-master.csv'

    def __init__(self, data_dir: str='data') -> None:
        self.data_dir = data_dir
        self.mapping_file = os.path.join(self.data_dir, 'indian_instruments.json')
        self._lock = threading.Lock()
        self.symbol_to_token: Dict[str, int] = {}
        self.token_to_symbol: Dict[int, str] = {}
        self._scheduler_thread: Optional[threading.Thread] = None
        self._running = False
        os.makedirs(self.data_dir, exist_ok=True)
        self.load_mappings_from_disk()
        if not self.symbol_to_token:
            self._seed_default_token_mappings()

    def _seed_default_token_mappings(self) -> None:
        """Seeds deterministic default instrument tokens for standard Indian equities & indices."""
        defaults = {'NSE:SBIN': 779521, 'NSE:RELIANCE': 738561, 'NSE:TCS': 2953217, 'NSE:INFY': 408065, 'NSE:HDFCBANK': 341249, 'NSE:ICICIBANK': 1270529, 'NSE:NIFTY 50': 256265, 'NSE:NIFTY BANK': 260105, 'BSE:SENSEX': 265, 'NFO:NIFTY24MARFUT': 8972101}
        with self._lock:
            for sym, token in defaults.items():
                self.symbol_to_token[sym] = token
                self.token_to_symbol[token] = sym

    def parse_kite_instruments_csv(self, csv_text: str) -> Dict[str, int]:
        """
        Parses Kite Connect master CSV file and returns symbol -> instrument_token map.
        CSV Columns: instrument_token, exchange_token, tradingsymbol, name, last_price,
                     expiry, strike, tick_size, lot_size, instrument_type, segment, exchange
        """
        new_map: Dict[str, int] = {}
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            try:
                token = int(row['instrument_token'])
                exchange = str(row.get('exchange', 'NSE')).strip().upper()
                trading_symbol = str(row.get('tradingsymbol', '')).strip().upper()
                if exchange and trading_symbol:
                    key = f'{exchange}:{trading_symbol}'
                    new_map[key] = token
            except (KeyError, ValueError):
                continue
        return new_map

    def parse_dhan_instruments_csv(self, csv_text: str) -> Dict[str, int]:
        """
        Parses DhanHQ master CSV scrip file and returns symbol -> token map.
        """
        new_map: Dict[str, int] = {}
        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            try:
                token = int(row.get('SEM_SMST_SECURITY_ID', row.get('SECURITY_ID', 0)))
                exchange = str(row.get('SEM_EXCHANGE_ID', row.get('EXCHANGE', 'NSE'))).strip().upper()
                trading_symbol = str(row.get('SEM_TRADING_SYMBOL', row.get('SYMBOL', ''))).strip().upper()
                if exchange and trading_symbol and (token > 0):
                    key = f'{exchange}:{trading_symbol}'
                    new_map[key] = token
            except (KeyError, ValueError):
                continue
        return new_map

    def download_master_instrument_list(self, broker: str='KITE') -> int:
        """
        Downloads the active daily master instrument list from broker API endpoint.
        Updates symbol_to_token and token_to_symbol maps and persists to disk.
        """
        broker_upper = broker.upper()
        url = self.DHAN_INSTRUMENTS_URL if broker_upper == 'DHAN' else self.KITE_INSTRUMENTS_URL
        _log.info('Downloading Indian master instrument list from %s [%s]...', broker_upper, url)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'EQATS/8.4'})
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                csv_bytes = resp.read()
                csv_text = csv_bytes.decode('utf-8', errors='ignore')
                if broker_upper == 'DHAN':
                    downloaded_map = self.parse_dhan_instruments_csv(csv_text)
                else:
                    downloaded_map = self.parse_kite_instruments_csv(csv_text)
                if downloaded_map:
                    with self._lock:
                        for sym, token in downloaded_map.items():
                            self.symbol_to_token[sym] = token
                            self.token_to_symbol[token] = sym
                    self.save_mappings_to_disk()
                    _log.info('Successfully updated %d instrument token mappings.', len(downloaded_map))
                    return len(downloaded_map)
        except Exception as e:
            _log.warning('Master instrument list download failed (%s). Using cached mappings.', e)
        return len(self.symbol_to_token)

    def get_instrument_token(self, symbol_key: str, broker: str='KITE') -> int:
        """
        Translates a human-readable ticker key (e.g., 'NSE:SBIN' or 'SBIN')
        into its active numeric session token ID.
        """
        key = symbol_key.strip().upper()
        if ':' not in key:
            key = f'NSE:{key}'
        with self._lock:
            if key in self.symbol_to_token:
                return self.symbol_to_token[key]
        db_token = database.get_instrument_token_from_db(key)
        if db_token:
            with self._lock:
                self.symbol_to_token[key] = db_token
                self.token_to_symbol[db_token] = key
            return db_token
        fallback_token = abs(hash(key)) % 9000000 + 100000
        with self._lock:
            self.symbol_to_token[key] = fallback_token
            self.token_to_symbol[fallback_token] = key
        return fallback_token

    def get_symbol_from_token(self, token: int) -> str:
        """
        Translates a numeric session token ID back to human-readable symbol key.
        """
        with self._lock:
            return self.token_to_symbol.get(token, f'UNKNOWN_{token}')

    def save_mappings_to_disk(self, filepath: Optional[str]=None) -> None:
        """Persists instrument mappings to disk as JSON."""
        target_path = filepath or self.mapping_file
        try:
            with self._lock:
                data = {'updated_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'symbol_to_token': self.symbol_to_token}
            with open(target_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            database.save_instrument_tokens_to_db(self.symbol_to_token)
            _log.info('Persisted instrument mappings to %s', target_path)
        except Exception as e:
            _log.error('Failed to persist instrument mappings: %s', e)

    def load_mappings_from_disk(self, filepath: Optional[str]=None) -> None:
        """Loads instrument mappings from disk JSON file."""
        target_path = filepath or self.mapping_file
        if not os.path.exists(target_path):
            return
        try:
            with open(target_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            symbol_map = data.get('symbol_to_token', {})
            with self._lock:
                for sym, token in symbol_map.items():
                    token_int = int(token)
                    self.symbol_to_token[sym] = token_int
                    self.token_to_symbol[token_int] = sym
            _log.info('Loaded %d instrument mappings from %s', len(symbol_map), target_path)
        except Exception as e:
            _log.warning('Failed to load instrument mappings from disk: %s', e)

    def calculate_seconds_until_target_time_ist(self, target_hour: int=8, target_minute: int=45) -> float:
        """Calculates exact seconds remaining until next target time in IST (08:45 AM IST)."""
        now_ist = datetime.now(IST_TIMEZONE)
        target_today = now_ist.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
        if now_ist >= target_today:
            target_next = target_today + timedelta(days=1)
        else:
            target_next = target_today
        return (target_next - now_ist).total_seconds()

    def start_daily_scheduler(self, target_time_ist: str='08:45', broker: str='KITE') -> None:
        """
        Starts background daemon thread that triggers daily master instrument downloads
        at the specified IST time (default: 08:45 AM IST).
        """
        if self._running:
            return
        self._running = True
        parts = target_time_ist.split(':')
        target_hour = int(parts[0])
        target_minute = int(parts[1])

        def _scheduler_loop() -> None:
            _log.info('Indian instrument token scheduler started (Target Time: %s AM IST).', target_time_ist)
            while self._running:
                delay = self.calculate_seconds_until_target_time_ist(target_hour, target_minute)
                _log.info('Scheduler sleeping for %.1f seconds until next 08:45 AM IST execution.', delay)
                slept = 0.0
                while self._running and slept < delay:
                    step = min(5.0, delay - slept)
                    time.sleep(step)
                    slept += step
                if self._running:
                    _log.info('Triggering scheduled 08:45 AM IST master instrument list download...')
                    self.download_master_instrument_list(broker=broker)
        self._scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True, name='IndianInstrumentSchedulerThread')
        self._scheduler_thread.start()

    def stop_daily_scheduler(self) -> None:
        """Stops the daily scheduler daemon thread."""
        self._running = False
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=2.0)
        _log.info('Indian instrument token scheduler stopped.')
global_indian_scheduler = IndianInstrumentScheduler()
