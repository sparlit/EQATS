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


""" Stores a scrip in an HDF5 file. Assumes the data exists locally."""

# This is more of a test scrip where we want to explore all ideas.

import pandas as pd
from corp_actions_nse import get_corp_action_csv

csv_filename = "500209.csv"

COL_NAMES = ["Date", "Open Price", "High Price", "Low Price", "Close Price", "No.of Shares", "Deliverable Quantity"]

infy = pd.read_csv(csv_filename, index_col="Date", usecols=COL_NAMES, parse_dates=True)
infy.columns = list("OHLCVD")

infy = infy[::-1]  # BSE scrip files are reverse latest first

print(infy[:10])

hdf_filename = "infy.h5"


c = get_corp_action_csv("infy")

corp_actions = {"corp_actions": c}

h5store = pd.HDFStore(hdf_filename)

h5store["infy"] = infy
h5store.get_storer("infy").attrs.corp_actions = c

h5store.close()

# open again for reading
h5store = pd.HDFStore(hdf_filename)

infy = h5store["infy"]
corp_actions = h5store.get_storer("infy").attrs.corp_actions

print(infy[:10])
for act in corp_actions:
    if act.action in ["B", "S"]:
        ts = pd.Timestamp(act.ex_date)
        ratio = act.ratio
        infy["O"][infy.index < ts] = infy["O"] * ratio
        infy["H"][infy.index < ts] = infy["H"] * ratio
        infy["L"][infy.index < ts] = infy["L"] * ratio
        infy["C"][infy.index < ts] = infy["C"] * ratio
        infy["V"][infy.index < ts] = infy["V"] / ratio
        infy["D"][infy.index < ts] = infy["D"] / ratio

print(infy[:10])
h5store.close()
