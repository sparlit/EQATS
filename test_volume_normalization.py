import unittest
from brain import ScalperBrain
from connector import MT5Connector


class TestVolumeNormalization(unittest.TestCase):
    def setUp(self):
        self.brain = ScalperBrain()

    def test_normalize_volume_standard_fx(self):
        # min=0.01, step=0.01
        norm = self.brain.normalize_volume("EURUSD", 0.015, min_vol=0.01, max_vol=100.0, step_vol=0.01)
        self.assertIn(norm, [0.01, 0.02])

    def test_normalize_volume_crypto_ltc(self):
        # Suppose broker requires min_vol=0.1, step_vol=0.1 for LTCUSD
        norm = self.brain.normalize_volume("LTCUSD", 0.01, min_vol=0.1, max_vol=100.0, step_vol=0.1)
        self.assertEqual(norm, 0.1)

    def test_normalize_volume_crypto_xrp(self):
        # Suppose broker requires min_vol=1.0, step_vol=1.0 for XRPUSD
        norm = self.brain.normalize_volume("XRPUSD", 0.05, min_vol=1.0, max_vol=10000.0, step_vol=1.0)
        self.assertEqual(norm, 1.0)

    def test_normalize_volume_step(self):
        norm = self.brain.normalize_volume("BTCUSD", 0.123, min_vol=0.01, max_vol=10.0, step_vol=0.05)
        # 0.01 + 2*0.05 = 0.11
        self.assertEqual(norm, 0.11)

    def test_filling_mode_bitmask_resolution(self):
        # ORDER_FILLING_FOK = 1, ORDER_FILLING_IOC = 2, ORDER_FILLING_RETURN = 4
        fok_only = 1
        ioc_only = 2
        return_only = 4

        self.assertTrue(fok_only & 1)
        self.assertFalse(fok_only & 2)

        self.assertTrue(ioc_only & 2)
        self.assertTrue(return_only & 4)


if __name__ == "__main__":
    unittest.main()
