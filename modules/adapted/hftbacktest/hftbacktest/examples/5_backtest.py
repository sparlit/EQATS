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
import multiprocessing
import os
import os.path
import subprocess
from datetime import datetime, timedelta

date_from = 20240501
date_to = 20240531

# The path for the converted npz files for the Rust version.
npz_path = "."

# The path where the backtesting result is saved.
out_path = "."

# The path where the example backtesting program, "gridtrading_backtest_args", is located.
backtest_program = "./gridtrading_backtest_args"

# Sets the number of processors for parallel processing during backtesting. The backtesting program itself doesn't use
# multiprocessing, but it runs multiple backtests for each pair in parallel to speed up the process.
num_processors = 8


with open("tickers.json") as f:
    tickers = json.load(f)


def backtest_rust(
    symbol,
    date_from_,
    date_to_,
    tick_size,
    lot_size,
    rel_half_spread,
    rel_grid_interval,
    grid_num,
    skew,
    order_qty,
    max_position,
):
    date = datetime.strptime(str(date_from_), "%Y%m%d")
    date_to_ = datetime.strptime(str(date_to_), "%Y%m%d")
    dates = []
    while date <= date_to_:
        dates.append(date.strftime("%Y%m%d"))
        date += timedelta(days=1)
    data_files = " ".join(
        [os.path.join(npz_path, f"{symbol}_{yyyymmdd}.npz") for yyyymmdd in dates]
    )
    latency_files = " ".join(
        [os.path.join(npz_path, f"latency_{yyyymmdd}.npz") for yyyymmdd in dates]
    )
    cmd = (
        f"{backtest_program} "
        f"--name {symbol} "
        f"--data-files {data_files} "
        f"--latency-files {latency_files} "
        f"--output-path {out_path} "
        f"--tick-size {tick_size} "
        f"--lot-size {lot_size} "
        f"--relative-half-spread {rel_half_spread} "
        f"--relative-grid-interval {rel_grid_interval} "
        f"--grid-num {grid_num} "
        f"--skew {skew} "
        f"--order-qty {order_qty} "
        f"--max-position {max_position} "
    )
    return_code = subprocess.call(cmd, shell=True)
    print(f"{symbol}: {return_code}\n")


# Sets parameters for the given symbol. You can find the best parameters for each pair through a grid search.
def params(symbol):
    tick_size = tickers[symbol]["tick_size"]
    lot_size = tickers[symbol]["lot_size"]
    min_qty = tickers[symbol]["min_qty"]
    rel_half_spread = 0.0005
    rel_grid_interval = 0.0005
    grid_num = 10
    skew = rel_half_spread / grid_num

    # Order quantity is set to be equivalent to about $100.
    if symbol.startswith("1000"):
        order_qty100 = round(
            (100 / (1000 * float(tickers[symbol]["weighted_avg_price"]))) / float(lot_size)
        ) * float(lot_size)
    else:
        order_qty100 = round(
            (100 / float(tickers[symbol]["weighted_avg_price"])) / float(lot_size)
        ) * float(lot_size)
    order_qty = max(float(min_qty), order_qty100)
    max_position = grid_num * order_qty

    return (
        symbol,
        date_from,
        date_to,
        tick_size,
        lot_size,
        rel_half_spread,
        rel_grid_interval,
        grid_num,
        skew,
        order_qty,
        max_position,
    )


args = [params(symbol) for symbol in tickers]
with multiprocessing.Pool(num_processors) as pool:
    pool.starmap(backtest_rust, args)
