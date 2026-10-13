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


"""Regression tests: no full or partial API key appears in core service logs."""

import hashlib
import logging
import os
import sys
from unittest.mock import MagicMock, patch

from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAKE_KEY = "test-api-key-not-real-12345678"


class TestWebsocketClientCloseLogging:
    """close_all_clients must not log API key material."""

    def test_close_error_does_not_leak_key(self, caplog):
        from services import websocket_client as wc_mod

        logger = logging.getLogger("services.websocket_client")
        old_propagate = logger.propagate
        logger.propagate = True
        logger.addHandler(caplog.handler)
        try:
            bad_client = MagicMock()
            bad_client.disconnect.side_effect = RuntimeError("connection reset")

            with wc_mod._client_lock:
                wc_mod._client_instances[FAKE_KEY] = bad_client

            with caplog.at_level(logging.ERROR):
                wc_mod.close_all_clients()

            assert "Error closing client: connection reset" in caplog.text
            assert FAKE_KEY not in caplog.text
            assert "test-api" not in caplog.text
        finally:
            logger.removeHandler(caplog.handler)
            logger.propagate = old_propagate


class TestOptionGreeksKeyLogging:
    """option_greeks must not log key prefixes on invalid key."""

    def test_invalid_key_log_uses_fingerprint(self):
        from flask_restx import Api
        from restx_api.option_greeks import api as greeks_api

        app = Flask(__name__)
        api = Api(app, prefix="/api/v1")
        api.add_namespace(greeks_api)

        with patch("restx_api.option_greeks.verify_api_key", return_value=False):
            with patch("restx_api.option_greeks.logger") as mock_logger:
                with app.test_client() as client:
                    response = client.post(
                        "/api/v1/optiongreeks",
                        json={
                            "apikey": FAKE_KEY,
                            "symbol": "NIFTY28NOV2424000CE",
                            "exchange": "NFO",
                        },
                    )

                assert response.status_code == 401
                mock_logger.warning.assert_called()
                log_msg = mock_logger.warning.call_args[0][0]
                assert FAKE_KEY not in log_msg
                assert FAKE_KEY[:10] not in log_msg
                expected_fingerprint = hashlib.sha256(FAKE_KEY.encode()).hexdigest()[:12]
                assert f"sha256:{expected_fingerprint}" in log_msg


class TestMultiOptionGreeksKeyLogging:
    """multi_option_greeks must not log key prefixes on invalid key."""

    def test_invalid_key_log_uses_fingerprint(self):
        from flask_restx import Api
        from restx_api.multi_option_greeks import api as multi_api

        app = Flask(__name__)
        api = Api(app, prefix="/api/v1")
        api.add_namespace(multi_api)

        with patch("restx_api.multi_option_greeks.verify_api_key", return_value=False):
            with patch("restx_api.multi_option_greeks.logger") as mock_logger:
                with app.test_client() as client:
                    response = client.post(
                        "/api/v1/multioptiongreeks",
                        json={
                            "apikey": FAKE_KEY,
                            "symbols": [
                                {
                                    "symbol": "NIFTY28NOV2424000CE",
                                    "exchange": "NFO",
                                }
                            ],
                        },
                    )

                assert response.status_code == 401
                mock_logger.warning.assert_called()
                log_msg = mock_logger.warning.call_args[0][0]
                assert FAKE_KEY not in log_msg
                assert FAKE_KEY[:10] not in log_msg
                expected_fingerprint = hashlib.sha256(FAKE_KEY.encode()).hexdigest()[:12]
                assert f"sha256:{expected_fingerprint}" in log_msg
