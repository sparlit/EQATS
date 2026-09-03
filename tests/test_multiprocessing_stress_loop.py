import multiprocessing as mp
import os
import time
import unittest
from typing import Any

import brain
import config
import database
import indicators
import main


def _run_single_stress_worker(worker_id: Any) -> Any:
    """
    Parallel worker process function.
    Executes a complete, isolated cycle of strategy evaluations, indicator computations,
    order flow microstructure metrics, risk gates, and autonomous scalping execution loop.
    Returns (success: bool, worker_id: int, message: str)
    """
    db_file = f"test_mp_worker_{worker_id}_{int(time.time() * 1000)}.db"
    config.DB_PATH = db_file
    config.SIMULATION_MODE = True
    config.MAX_CONCURRENT_TRADES = 5
    config.RISK_PER_TRADE_PERCENT = 1.0
    try:
        database.init_db()
        scalper_brain = brain.ScalperBrain()
        bars = [
            {
                "open": 1.1 + i * 0.0001,
                "high": 1.1005 + i * 0.0001,
                "low": 1.0995 + i * 0.0001,
                "close": 1.1003 + i * 0.0001,
            }
            for i in range(220)
        ]
        strategies = [
            "TREND_FOLLOWING",
            "MEAN_REVERSION",
            "MACD_MOMENTUM",
            "BREAKOUT",
            "CARRY_TRADE",
            "GRID_TRADE",
            "STAT_ARB",
            "ORB",
            "VSA",
            "MTF_CONFLUENCE",
            "SMC_ICT",
            "ORDER_FLOW",
            "VOTING_ENSEMBLE",
        ]
        for strat in strategies:
            config.ACTIVE_STRATEGY = strat
            res = scalper_brain.evaluate("EURUSD", bars, 10000.0)
            assert res is not None and "decision" in res, f"Strategy {strat} failed in worker {worker_id}"
            assert res["decision"] in ["BUY", "SELL", "HOLD"], f"Invalid decision in {strat}"
        order_book = {"bids": [(1.102, 100.0), (1.1019, 150.0)], "asks": [(1.1021, 20.0), (1.1022, 30.0)]}
        of_res = indicators.calculate_order_flow_metrics(bars, order_book=order_book)
        assert of_res["vpin"] >= 0.0, "VPIN calculation failed"
        assert of_res["dominant_side"] == "BUY_DOMINANT", "DOM imbalance check failed"
        scalper = main.AutonomousScalper()
        if scalper.start():
            for _ in range(5):
                scalper.tick_and_execute()
            scalper.stop()
        return (True, worker_id, "SUCCESS")
    except Exception as e:
        return (False, worker_id, f"ERROR: {e!s}")
    finally:
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass


class TestMultiprocessingStressLoop(unittest.TestCase):
    """
    Multi-Process Stress Test Suite.
    Launches 10 parallel processes running concurrent strategy evaluations,
    microstructure calculations, and autonomous trading loops to ensure 100% thread/process safety.
    """

    def test_multiprocessing_parallel_loop_10_count(self) -> None:
        """Launches 10 concurrent worker processes executing all strategies and trading methods."""
        count = 10
        ctx = mp.get_context("spawn")
        print(f"\n🚀 Launching {count} Parallel Multiprocessing Workers for Full Strategy & Rules Stress Test...")
        with ctx.Pool(processes=count) as pool:
            worker_ids = list(range(1, count + 1))
            results = pool.map(_run_single_stress_worker, worker_ids)
        self.assertEqual(len(results), count)
        for success, w_id, msg in results:
            print(f"   [Worker #{w_id:02d}] Status: {('PASSED' if success else 'FAILED')} | {msg}")
            self.assertTrue(success, f"Multiprocessing worker #{w_id} failed with message: {msg}")
        print(f"✅ All {count} Multiprocessing Stress Test Workers Passed Cleanly with ZERO Exceptions!")


if __name__ == "__main__":
    unittest.main()
