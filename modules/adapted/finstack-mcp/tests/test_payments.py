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


import json
from pathlib import Path

from finstack import payments
from finstack.config import UserTier


def _sign(secret: str, payload: bytes) -> str:
    import hashlib
    import hmac

    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def _stripe_signature(secret: str, payload: bytes, timestamp: str = "1234567890") -> str:
    import hashlib
    import hmac

    signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
    digest = hmac.new(
        secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def test_razorpay_assigns_enterprise_for_high_value_payment(monkeypatch):
    db_path = Path("tests") / "test_razorpay_users.db"
    if db_path.exists():
        db_path.unlink()
    monkeypatch.setattr(payments, "DB_PATH", str(db_path))

    payload = json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "email": "enterprise@example.com",
                        "id": "pay_ent_123",
                        "amount": 1500000,
                    }
                }
            },
        }
    ).encode("utf-8")

    secret = "razor_secret"
    result = payments.handle_razorpay_webhook(payload, _sign(secret, payload), secret)

    assert result["tier"] == UserTier.ENTERPRISE.value
    if db_path.exists():
        db_path.unlink()


def test_stripe_assigns_enterprise_for_high_value_checkout(monkeypatch):
    db_path = Path("tests") / "test_stripe_users.db"
    if db_path.exists():
        db_path.unlink()
    monkeypatch.setattr(payments, "DB_PATH", str(db_path))

    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer_email": "enterprise@example.com",
                    "payment_intent": "pi_123",
                    "amount_total": 19900,
                }
            },
        }
    ).encode("utf-8")

    secret = "stripe_secret"
    signature = _stripe_signature(secret, payload)
    result = payments.handle_stripe_webhook(payload, signature, secret)

    assert result["tier"] == UserTier.ENTERPRISE.value
    if db_path.exists():
        db_path.unlink()
