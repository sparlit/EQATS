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
from pathlib import Path

import setup_doctor


class LocalSetupTests(unittest.TestCase):
    def audit(self, wallet_fields):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.env"
            path.write_text("POLY_PRIVATE_KEY=" + "1" * 64 + "\n" + wallet_fields, encoding="utf-8")
            return setup_doctor._collect_audit(path)

    def test_eoa_does_not_need_hosted_credentials(self):
        audit = self.audit("POLY_SIGNATURE_TYPE=0\nEVPOLY_ALPHA_AUTO_ONBOARD=false\n")
        self.assertEqual(audit["blocking_missing_labels"], [])
        self.assertEqual(audit["manual_missing_labels"], [])

    def test_proxy_can_trade_without_optional_relayer_credentials(self):
        audit = self.audit("POLY_SIGNATURE_TYPE=1\nPOLY_PROXY_WALLET_ADDRESS=0x" + "2" * 40)
        self.assertEqual(audit["blocking_missing_labels"], [])
        self.assertEqual(
            audit["manual_missing_labels"], ["Relayer API Key", "Relayer API Key Address"]
        )

    def test_deposit_mode_is_preserved_and_requires_its_funder(self):
        self.assertEqual(
            self.audit("POLY_SIGNATURE_TYPE=3\n")["blocking_missing_labels"], ["Deposit Wallet"]
        )
        audit = self.audit("POLY_SIGNATURE_TYPE=3\nPOLY_DEPOSIT_WALLET_ADDRESS=0x" + "3" * 40)
        self.assertEqual(audit["manual_missing_labels"], [])


if __name__ == "__main__":
    unittest.main()
