import unittest
import datetime
import database
import brain
import config
import main

class TestScalperEnhancements(unittest.TestCase):

    def setUp(self):
        database.init_db()
        self.scalper_brain = brain.ScalperBrain()

    def test_leverage_persistence(self):
        # Save broker credentials with custom leverage
        database.save_broker_credentials(
            server="TestServer",
            account_id="99999",
            password="secretpassword",
            leverage="1:888",
            broker_name="Custom Gateway",
            environment="Demo"
        )
        creds = database.get_broker_credentials()
        self.assertEqual(creds["leverage"], "1:888")
        self.assertEqual(creds["broker_name"], "Custom Gateway")

    def test_fixed_001_lot_size(self):
        history_bars = [
            {'open': 1.1000 + i*0.0001, 'high': 1.1005 + i*0.0001, 'low': 1.0995 + i*0.0001, 'close': 1.1002 + i*0.0001}
            for i in range(250)
        ]
        res = self.scalper_brain.evaluate("EURUSD", history_bars, 50000.0)
        if res["decision"] in ["BUY", "SELL"]:
            self.assertEqual(res["lot_size"], 0.01)

        lot_calc = self.scalper_brain._calculate_lot_size("EURUSD", 100000.0, 0.0020)
        self.assertEqual(lot_calc, 0.01)

    def test_symbol_floating_loss_gate(self):
        # Log a dummy open trade on EURUSD with floating loss
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trades WHERE symbol = 'EURUSD' AND status = 'OPEN'")
        now_iso = datetime.datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO trades (ticket, symbol, direction, open_price, sl, tp, lot_size, status, profit, open_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
        """, ("TEST_LOSS_001", "EURUSD", "BUY", 1.1000, 1.0950, 1.1100, 0.01, -2.50, now_iso))
        conn.commit()
        conn.close()

        history_bars = [
            {'open': 1.1000 + i*0.0001, 'high': 1.1005 + i*0.0001, 'low': 1.0995 + i*0.0001, 'close': 1.1002 + i*0.0001}
            for i in range(250)
        ]
        res = self.scalper_brain.evaluate("EURUSD", history_bars, 10000.0)
        self.assertEqual(res["decision"], "HOLD")
        self.assertIn("Symbol Loss Protection Gate", res["explanation"])

        # Clean up dummy trade
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trades WHERE ticket = 'TEST_LOSS_001'")
        conn.commit()
        conn.close()

if __name__ == "__main__":
    unittest.main()
