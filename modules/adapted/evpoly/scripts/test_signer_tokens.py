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


import tempfile
import unittest

import remote_onboard
import setup_doctor


class RemoteOnboardTests(unittest.TestCase):
    def test_relayer_submit_signer_url_uses_default(self) -> None:
        runtime_cfg = remote_onboard._resolve_runtime_config({"runtime": {}})
        assert runtime_cfg["relayer_submit_signer_url"] == remote_onboard.DEFAULT_RELAYER_SUBMIT_SIGNER_URL

    def test_relayer_submit_signer_url_prefers_runtime_value(self) -> None:
        runtime_cfg = remote_onboard._resolve_runtime_config(
            {"runtime": {"relayer_submit_signer_url": "https://example.test/sign/submit"}}
        )
        assert runtime_cfg["relayer_submit_signer_url"] == "https://example.test/sign/submit"

    def test_relayer_submit_signer_url_accepts_legacy_submit_alias(self) -> None:
        runtime_cfg = remote_onboard._resolve_runtime_config(
            {"runtime": {"submit_signer_url": "https://example.test/legacy-submit"}}
        )
        assert runtime_cfg["relayer_submit_signer_url"] == "https://example.test/legacy-submit"


class SetupDoctorTests(unittest.TestCase):
    def test_doctor_user_facing_baseline_has_no_order_posting_signer_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = setup_doctor.run_doctor(setup_doctor.Path(tmpdir) / ".env")
        item_keys = [item["key"] for item in result["items"]]
        assert "EVPOLY_ALPHA_KEY" in item_keys
        assert all("ORDER_SIGNER" not in key for key in item_keys)
        assert all("BUILDER_REMOTE" not in key for key in item_keys)


if __name__ == "__main__":
    unittest.main()
