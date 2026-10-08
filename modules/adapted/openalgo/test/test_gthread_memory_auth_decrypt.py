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


"""Failed token decryptions must not retain one fingerprint per bad token forever."""


def test_failed_decrypt_dedupe_stays_bounded_across_unique_tokens(monkeypatch):
    from database import auth_db

    auth_db._decrypt_failure_fingerprints.clear()
    failures = []
    repeats = []
    monkeypatch.setattr(auth_db.logger, "exception", failures.append)
    monkeypatch.setattr(auth_db.logger, "debug", repeats.append)
    try:
        for index in range(400):
            assert auth_db.decrypt_token(f"bad-ciphertext-{index}") is None

        assert len(auth_db._decrypt_failure_fingerprints) <= 256
        assert len(failures) == 400

        assert auth_db.decrypt_token("bad-ciphertext-399") is None
        assert len(failures) == 400
        assert len(repeats) == 1
    finally:
        auth_db._decrypt_failure_fingerprints.clear()
