import os
import sys
import time
import tempfile
import sqlite3

# Ensure src/ is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import database

def benchmark_get_daily_profit(iterations: int = 1000):
    # Use temporary file database for realistic disk I/O benchmark
    temp_dir = tempfile.mkdtemp()
    db_file = os.path.join(temp_dir, "bench_test.db")
    config.DB_PATH = db_file

    database.init_db()

    # Seed some sample trades
    conn = database.get_connection()
    cursor = conn.cursor()
    today_str = "2026-03-31"
    for i in range(50):
        cursor.execute(
            "INSERT INTO trades (ticket, symbol, direction, open_price, open_time, sl, tp, lot_size, status, close_price, close_time, profit, close_reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"TICK_{i}", "EURUSD", "BUY", 1.0500, f"{today_str}T09:00:00", 1.0400, 1.0600, 0.1, "CLOSED", 1.0550, f"{today_str}T10:00:00", 50.0, "TP")
        )
    conn.commit()
    conn.close()

    # Warmup
    _ = database.get_daily_profit(today_str)

    start_time = time.perf_counter()
    for _ in range(iterations):
        _ = database.get_daily_profit(today_str)
    end_time = time.perf_counter()

    elapsed = end_time - start_time
    avg_latency_ms = (elapsed / iterations) * 1000.0
    ops_per_sec = iterations / elapsed

    print(f"--- Benchmark Baseline ---")
    print(f"Iterations: {iterations}")
    print(f"Total time: {elapsed:.4f} seconds")
    print(f"Average latency: {avg_latency_ms:.4f} ms per call")
    print(f"Throughput: {ops_per_sec:.2f} ops/sec")

    # Clean up
    if os.path.exists(db_file):
        os.remove(db_file)
    if os.path.exists(db_file + ".salt"):
        os.remove(db_file + ".salt")

if __name__ == "__main__":
    benchmark_get_daily_profit(2000)
