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


import csv

import pandas as pd


def get_nse_symbols(csv_path):
    """
    Reads NSE symbols from the provided CSV file.
    Assumes the symbol is in the third column (index 2).
    """
    symbols = []
    try:
        with open(csv_path) as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            for row in reader:
                if len(row) > 2:
                    symbols.append(row[2])
    except FileNotFoundError:
        print(f"Error: File not found at {csv_path}")
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return symbols


def load_equity_list(csv_path):
    """
    Reads the Equity_List.csv and returns a dictionary mapping Symbol to details.
    Returns: {Symbol: {name: ..., isin: ..., etc.}}
    """
    equity_map = {}
    try:
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Map CSV columns to what we might need.
                # Based on file view: Security Code,Issuer Name,Security Id,Security Name,Status,Group,Face Value,ISIN No,Industry,Instrument,Sector Name,Industry New Name,Igroup Name,ISubgroup Name
                # 'Security Id' seems to be the Symbol.
                symbol = row.get("Security Id")
                if symbol:
                    equity_map[symbol] = {
                        "name": row.get("Security Name"),
                        "isin": row.get("ISIN No"),
                        "industry": row.get("Industry"),
                        "sector": row.get("Sector Name"),
                    }
    except FileNotFoundError:
        print(f"Error: Equity List file not found at {csv_path}")
    except Exception as e:
        print(f"Error reading Equity List CSV: {e}")
    return equity_map


def get_symbols_from_new_list(csv_path):
    """
    Reads symbols from the new equity list CSV (first column).
    """
    symbols = []
    try:
        with open(csv_path) as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            for row in reader:
                if len(row) > 0:
                    symbols.append(row[0])  # SYMBOL is in the first column
    except FileNotFoundError:
        print(f"Error: File not found at {csv_path}")
    except Exception as e:
        print(f"Error reading New Equity List CSV: {e}")
    return symbols


def get_remaining_symbols(full_list_path, subset_list_path):
    """
    Returns symbols present in full_list but NOT in subset_list.
    """
    full_list = set(get_symbols_from_new_list(full_list_path))
    subset_list = set(get_nse_symbols(subset_list_path))

    remaining = list(full_list - subset_list)
    remaining.sort()
    return remaining


def load_full_equity_list(csv_path):
    """
    Reads the new full equity list and returns a dictionary mapping Symbol to details.
    Columns: SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
    """
    equity_map = {}
    try:
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get("SYMBOL")
                if symbol:
                    equity_map[symbol] = {
                        "name": row.get("NAME OF COMPANY"),
                        "isin": row.get("ISIN NUMBER"),
                        "industry": None,  # Not available in this file
                        "sector": None,  # Not available in this file
                    }
    except FileNotFoundError:
        print(f"Error: Full Equity List file not found at {csv_path}")
    except Exception as e:
        print(f"Error reading Full Equity List CSV: {e}")
    return equity_map
