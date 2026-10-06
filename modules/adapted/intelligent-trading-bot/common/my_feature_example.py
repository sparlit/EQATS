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


from common.model_store import *

"""
Example of a feature
"""


def my_feature_example(
    df, config: dict, global_config: dict, model_store: ModelStore, last_rows: int = 0
):
    """
    Add a parameter to the column or multiply by this parameter
    """

    column_name = config.get("columns")
    if not column_name:
        raise ValueError(f"The 'columns' parameter must be a non-empty string. {type(column_name)}")
    elif not isinstance(column_name, str):
        raise ValueError(f"Wrong type of the 'columns' parameter: {type(column_name)}")
    elif column_name not in df.columns:
        raise ValueError(
            f"{column_name} does not exist  in the input data. Existing columns: {df.columns.to_list()}"
        )

    function = config.get("function")
    if not isinstance(function, str):
        raise ValueError(f"Wrong type of the 'function' parameter: {type(function)}")
    if function not in ["add", "mul"]:
        raise ValueError(f"Unknown function name {function}. Only 'add' or 'mul' are possible")

    parameter = config.get("parameter")  # Numeric parameter
    if not isinstance(parameter, (float, int)):
        raise ValueError(f"Wrong 'parameter' type {type(parameter)}. Only numbers are supported")

    names = config.get("names")  # Output feature name
    if not names:
        names = f"{column_name}_{function}"

    if function == "add":
        df[names] = df[column_name] + parameter
    elif function == "mul":
        df[names] = df[column_name] * parameter

    print(f"Finished computing feature '{names}'")

    return df, [names]
