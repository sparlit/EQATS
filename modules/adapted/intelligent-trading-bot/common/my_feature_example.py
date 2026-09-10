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


from pathlib import Path
from typing import Union

import pandas as pd
from common.model_store import *

"""
Example of a feature
"""


def my_feature_example(df, config: dict, global_config: dict, model_store: ModelStore, last_rows: int = 0):
    """
    Add a parameter to the column or multiply by this parameter
    """

    column_name = config.get("columns")
    if not column_name:
        msg = f"The 'columns' parameter must be a non-empty string. {type(column_name)}"
        raise ValueError(msg)
    if not isinstance(column_name, str):
        msg = f"Wrong type of the 'columns' parameter: {type(column_name)}"
        raise ValueError(msg)
    if column_name not in df.columns:
        msg = f"{column_name} does not exist  in the input data. Existing columns: {df.columns.to_list()}"
        raise ValueError(msg)

    function = config.get("function")
    if not isinstance(function, str):
        msg = f"Wrong type of the 'function' parameter: {type(function)}"
        raise ValueError(msg)
    if function not in ["add", "mul"]:
        msg = f"Unknown function name {function}. Only 'add' or 'mul' are possible"
        raise ValueError(msg)

    parameter = config.get("parameter")  # Numeric parameter
    if not isinstance(parameter, (float, int)):
        msg = f"Wrong 'parameter' type {type(parameter)}. Only numbers are supported"
        raise ValueError(msg)

    names = config.get("names")  # Output feature name
    if not names:
        names = f"{column_name}_{function}"

    if function == "add":
        df[names] = df[column_name] + parameter
    elif function == "mul":
        df[names] = df[column_name] * parameter

    print(f"Finished computing feature '{names}'")

    return df, [names]
