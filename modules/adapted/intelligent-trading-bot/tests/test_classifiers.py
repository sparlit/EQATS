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


import pytest
from common.classifier_gb import train_predict_gb
from common.classifier_lc import train_predict_lc
from common.classifier_nn import train_predict_nn
from common.utils import *


def test_nan_handling_predict():
    """Predicted input has nans. These nans rows have to be removed before prediction but the output has to contain all rows including these nan rows."""

    is_scale = True  # Try with both False and True (explicitly)

    df_X = pd.DataFrame({"x": [1, 2, 3, 2, 1], "y": [0, 1, 0, 1, 0]})  # Input has no nans
    df_X_test = pd.DataFrame({"x": [1, 2, None, 2, np.nan], "y": [0, 1, 0, 1, 0]})  # Has nans

    test_hat = train_predict_gb(
        df_X[["x"]],
        df_X["y"],
        df_X_test[["x"]],
        model_config={
            "is_scale": is_scale,
            "objective": "cross_entropy",
            "max_depth": 1,
            "learning_rate": 0.1,
            "num_boost_round": 2,
        },
    )
    assert len(test_hat) == 5
    assert test_hat.isnull().sum() == 2

    test_hat = train_predict_nn(
        df_X[["x"]],
        df_X["y"],
        df_X_test[["x"]],
        model_config={"is_scale": is_scale, "learning_rate": 0.5, "n_epochs": 1, "bs": 2},
    )
    assert len(test_hat) == 5
    assert test_hat.isnull().sum() == 2

    test_hat = train_predict_lc(
        df_X[["x"]],
        df_X["y"],
        df_X_test[["x"]],
        model_config={"is_scale": is_scale},
    )
    assert len(test_hat) == 5
    assert test_hat.isnull().sum() == 2
