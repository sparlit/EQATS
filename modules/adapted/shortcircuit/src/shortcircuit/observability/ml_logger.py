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


"""
ML Data Logger Module
Collects training data for reversal pattern prediction.

Best Practices Implemented:
1. Parquet format (efficient, typed, ML-ready)
2. Atomic writes (no corruption on crash)
3. Schema versioning
4. Unique observation IDs
5. Separate feature logging from outcome logging
6. Daily file rotation
7. Automatic backup

Usage:
    logger = MLDataLogger()
    obs_id = logger.log_observation(symbol, features)  # At signal time
    logger.update_outcome(obs_id, outcome)  # EOD
"""

import datetime
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

logger = logging.getLogger("MLDataLogger")
IST = ZoneInfo("Asia/Kolkata")

# Schema version - increment when changing feature set
SCHEMA_VERSION = "1.2.0"

# Feature columns for ML training
FEATURE_COLUMNS = [
    # Identifiers
    "obs_id",  # Unique observation ID
    "schema_version",  # For backward compatibility
    "date",  # YYYY-MM-DD
    "time",  # HH:MM:SS
    "timestamp_ist",  # ISO-8601 signal timestamp with Asia/Kolkata offset
    "symbol",  # NSE:SYMBOL-EQ
    # Price Context
    "ltp",  # Last traded price at signal
    "prev_close",  # Previous day close
    "day_high",  # Day high at signal time
    "day_low",  # Day low at signal time
    "gain_pct",  # % gain from prev close
    # VWAP Features
    "vwap",  # Current VWAP
    "vwap_distance_pct",  # Distance from VWAP as %
    "vwap_sd",  # Standard deviations from VWAP
    "vwap_slope",  # VWAP slope (trend)
    # Volume Features
    "volume_current",  # Volume of setup candle
    "volume_avg_20",  # 20-candle average volume
    "rvol",  # Relative volume (current/avg)
    # Structure Features
    "pattern",  # Pattern type (SHOOTING_STAR, etc.)
    "candle_body_pct",  # Body as % of range
    "upper_wick_pct",  # Upper wick as % of range
    "lower_wick_pct",  # Lower wick as % of range
    # Pattern Bonus Features
    "stretch_score",  # Score representing the degree of price extension
    "vol_fade_ratio",  # Volume fade ratio
    "confidence",  # Tiered strategy confidence (MEDIUM, HIGH, EXTREME)
    "pattern_bonus",  # Any bonus narrative text
    # Confluence Count
    "num_confirmations",  # Number of pro_conf items
    "confirmations",  # JSON list of confirmations
    # Context
    "nifty_trend",  # UP/DOWN/RANGE
    "sector",  # Extracted from symbol if possible
    "time_bucket",  # OPEN/MID/CLOSE (market phase)
    "direction",  # SHORT or LONG (Phase 96.5)
    # Risk Parameters (for EOD Simulation)
    "atr",
    "sl_price",
    "tp_price",
    # OI (if available)
    "oi",  # Open interest
    "oi_change_pct",  # OI change from previous
    # Labels (filled at EOD)
    "outcome",  # WIN/LOSS/BREAKEVEN
    "exit_price",  # Actual or simulated exit
    "max_favorable",  # Max favorable excursion (MFE)
    "max_adverse",  # Max adverse excursion (MAE)
    "pnl_pct",  # P&L as % of entry
    "hold_time_mins",  # How long position held
    "label_source",  # LIVE/GHOST/LEGACY
    "exit_reason",  # SL_HIT/TP_HIT/EOD_SQUAREOFF/etc.
]


class MLDataLogger:
    """
    Production-grade ML data logger.
    Logs observations at signal time, updates outcomes at EOD.
    """

    def __init__(self, data_dir: str = "data/ml", session_date: str | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Daily file path
        self.today = session_date or datetime.datetime.now(IST).date().isoformat()
        self.daily_file = self.data_dir / f"observations_{self.today}.parquet"
        self.backup_file = self.data_dir / f"observations_{self.today}.csv"

        # In-memory buffer for atomic writes
        self._buffer: list = []
        self._lock = threading.Lock()

        # Load existing data if any
        self._load_existing()

        logger.info(f"[ML] Data logger initialized. File: {self.daily_file}")

    def _roll_date_if_needed(self) -> None:
        """
        Roll to a new daily file when the session date changes.

        `self.today` was captured once at construction, and this logger is a
        process-wide singleton. Any run that survives midnight — which the
        post-market handler explicitly does, sleeping until the next open — kept
        appending to the previous day's parquet and re-saving that day's whole
        buffer, mislabelling every new observation.
        """
        current = datetime.datetime.now(IST).date().isoformat()
        if current == self.today:
            return

        with self._lock:
            if current == self.today:  # re-check under lock
                return
            previous = self.today
            self.today = current
            self.daily_file = self.data_dir / f"observations_{current}.parquet"
            self.backup_file = self.data_dir / f"observations_{current}.csv"
            self._buffer = []

        logger.info("[ML] Rolled session file %s → %s", previous, current)
        self._load_existing()

    def _load_existing(self):
        """Load existing observations for today if file exists."""
        if self.daily_file.exists():
            try:
                df = pd.read_parquet(self.daily_file)
                self._buffer = [self._normalize_record(r) for r in df.to_dict("records")]
                logger.info(f"[ML] Loaded {len(self._buffer)} existing observations")
            except Exception as e:
                logger.error(f"[ML] Error loading existing data: {e}")
                # Try backup
                if self.backup_file.exists():
                    df = pd.read_csv(self.backup_file)
                    self._buffer = [self._normalize_record(r) for r in df.to_dict("records")]

    def _normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Backfill new schema fields without rewriting old files on read."""
        record.setdefault("timestamp_ist", None)
        record.setdefault("label_source", None)
        record.setdefault("exit_reason", None)
        return record

    def _dataframe_from_buffer(self) -> pd.DataFrame:
        df = pd.DataFrame([self._normalize_record(dict(r)) for r in self._buffer])
        for col in FEATURE_COLUMNS:
            if col not in df.columns:
                df[col] = None
        ordered = FEATURE_COLUMNS + [c for c in df.columns if c not in FEATURE_COLUMNS]
        return df[ordered]

    def _save(self):
        """Atomic save to parquet + CSV backup."""
        with self._lock:
            if not self._buffer:
                return

            try:
                df = self._dataframe_from_buffer()

                # Parquet (primary)
                temp_file = self.daily_file.with_suffix(".tmp")
                df.to_parquet(temp_file, index=False)
                temp_file.replace(self.daily_file)

                # CSV backup
                df.to_csv(self.backup_file, index=False)

            except Exception as e:
                logger.error(f"[ML] Save error: {e}")

    def log_observation(self, symbol: str, ltp: float, features: dict[str, Any]) -> str:
        """
        Log a new observation when a signal is detected.
        Returns observation ID for later outcome update.
        """
        self._roll_date_if_needed()
        obs_id = str(uuid.uuid4())[:8]  # Short unique ID
        now = datetime.datetime.now(IST)

        # Determine time bucket
        hour = now.hour
        if hour < 10:
            time_bucket = "OPEN"
        elif hour < 14:
            time_bucket = "MID"
        else:
            time_bucket = "CLOSE"

        observation = {
            # Identifiers
            "obs_id": obs_id,
            "schema_version": SCHEMA_VERSION,
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timestamp_ist": now.isoformat(timespec="seconds"),
            "symbol": symbol,
            # From features dict
            "ltp": ltp,
            "prev_close": features.get("prev_close", 0),
            "day_high": features.get("day_high", ltp),
            "day_low": features.get("day_low", ltp),
            "gain_pct": features.get("gain_pct", 0),
            "vwap": features.get("vwap", 0),
            "vwap_distance_pct": features.get("vwap_distance_pct", 0),
            "vwap_sd": features.get("vwap_sd", 0),
            "vwap_slope": features.get("vwap_slope", 0),
            "volume_current": features.get("volume_current", 0),
            "volume_avg_20": features.get("volume_avg_20", 0),
            "rvol": features.get("rvol", 0),
            "pattern": features.get("pattern", "UNKNOWN"),
            "candle_body_pct": features.get("candle_body_pct", 0),
            "upper_wick_pct": features.get("upper_wick_pct", 0),
            "lower_wick_pct": features.get("lower_wick_pct", 0),
            # Strategy quality features. Declared in FEATURE_COLUMNS and passed by
            # _finalize_signal, but never copied here — so every row written before
            # this fix has them null (99/99 across 27 session files). They are the
            # most discriminative features the strategy produces.
            "stretch_score": features.get("stretch_score", 0.0),
            "vol_fade_ratio": features.get("vol_fade_ratio", 0.0),
            "confidence": features.get("confidence", "MEDIUM"),
            "pattern_bonus": features.get("pattern_bonus", "None"),
            "dom_ratio": features.get("dom_ratio", 1.0),
            "bid_ask_spread": features.get("bid_ask_spread", 0),
            "num_confirmations": features.get("num_confirmations", 0),
            "confirmations": json.dumps(features.get("confirmations", [])),
            "is_round_number": features.get("is_round_number", False),
            "is_bad_high": features.get("is_bad_high", False),
            "is_trapped": features.get("is_trapped", False),
            "is_absorption": features.get("is_absorption", False),
            "nifty_trend": features.get("nifty_trend", "UNKNOWN"),
            "sector": self._extract_sector(symbol),
            "time_bucket": time_bucket,
            "direction": features.get("direction", "SHORT"),
            # Risk Parameters
            "atr": features.get("atr", 0),
            "sl_price": features.get("sl_price", 0),
            "tp_price": features.get("tp_price", 0),
            "leverage": features.get("leverage", 5.0),
            "oi": features.get("oi", 0),
            "oi_change_pct": features.get("oi_change_pct", 0),
            # How the trade is meant to be exited, and the levels a ghost audit
            # needs to grade it the way the engine would actually have traded it.
            # Absent (None) for BackToVWAPShort rows.
            "exit_profile": features.get("exit_profile"),
            "trigger_price": features.get("trigger_price"),
            "coil_high": features.get("coil_high"),
            "armed_at": features.get("armed_at"),
            # Labels (empty, filled at EOD)
            "outcome": None,
            "exit_price": None,
            "max_favorable": None,
            "max_adverse": None,
            "pnl_pct": None,
            "hold_time_mins": None,
            "label_source": None,
            "exit_reason": None,
        }

        with self._lock:
            self._buffer.append(observation)

        self._save()
        logger.info(f"[ML] Logged observation {obs_id} for {symbol}")

        return obs_id

    def update_outcome(
        self,
        obs_id: str,
        outcome: str,
        exit_price: float,
        max_favorable: float = 0,
        max_adverse: float = 0,
        hold_time_mins: int = 0,
        pnl_pct: float | None = None,
        label_source: str = "LIVE",
        exit_reason: str | None = None,
    ) -> bool:
        """
        Update the outcome for an observation (called at EOD or trade close).
        """
        with self._lock:
            for obs in self._buffer:
                if obs["obs_id"] == obs_id:
                    self._normalize_record(obs)
                    entry = obs["ltp"]
                    if pnl_pct is None:
                        # Fallback for old calls without pnl_pct passed
                        pnl_pct = ((entry - exit_price) / entry) * 100 if entry > 0 else 0

                    obs["outcome"] = outcome
                    obs["exit_price"] = exit_price
                    obs["max_favorable"] = max_favorable
                    obs["max_adverse"] = max_adverse
                    obs["pnl_pct"] = pnl_pct
                    obs["hold_time_mins"] = hold_time_mins
                    obs["label_source"] = label_source
                    obs["exit_reason"] = exit_reason

                    logger.info(f"[ML] Updated outcome for {obs_id}: {outcome} ({pnl_pct:.2f}%)")
                    found = True
                    break
            else:
                found = False

        self._save()
        if not found:
            logger.warning(f"[ML] Outcome update skipped; obs_id not found: {obs_id}")
        return found

    def update_fields(self, obs_id: str, **fields: Any) -> bool:
        """Overwrite feature fields on an existing observation (not its label)."""
        with self._lock:
            for obs in self._buffer:
                if obs["obs_id"] == obs_id:
                    obs.update(fields)
                    found = True
                    break
            else:
                found = False
        if found:
            self._save()
        return found

    def _extract_sector(self, symbol: str) -> str:
        """Extract sector from symbol (simplified)."""
        # Could be enhanced with a sector mapping file
        symbol_clean = symbol.replace("NSE:", "").replace("-EQ", "")

        # Basic sector keywords
        if any(x in symbol_clean for x in ["BANK", "FIN", "HDFC", "ICICI", "KOTAK"]):
            return "BANKING"
        elif any(x in symbol_clean for x in ["STEEL", "TATA", "JSW", "JINDAL"]):
            return "METAL"
        elif any(x in symbol_clean for x in ["PHARMA", "SUN", "CIPLA", "DR"]):
            return "PHARMA"
        elif any(x in symbol_clean for x in ["TECH", "INFY", "TCS", "WIPRO"]):
            return "IT"
        elif any(x in symbol_clean for x in ["OIL", "RELIANCE", "ONGC", "BPCL"]):
            return "ENERGY"
        else:
            return "OTHER"

    def get_unlabeled_observations(self, session_date: str | None = None) -> pd.DataFrame:
        """Get observations that haven't been labeled yet."""
        with self._lock:
            unlabeled = [
                self._normalize_record(dict(obs))
                for obs in self._buffer
                if obs["outcome"] is None
                and (session_date is None or obs.get("date") == session_date)
            ]
            return pd.DataFrame(unlabeled)


# Singleton instance
_ml_logger: MLDataLogger | None = None


def get_ml_logger() -> MLDataLogger:
    """Get singleton ML logger instance."""
    global _ml_logger
    if _ml_logger is None:
        _ml_logger = MLDataLogger()
    return _ml_logger
