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


import datetime as dt
import math
from datetime import date, timedelta

import matplotlib.pyplot as plt
import nselib
import numpy as np
import pandas as pd
import seaborn as sns
import yfinance as yf
from pandas.plotting import autocorrelation_plot, lag_plot
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler
from sklearn.utils.class_weight import compute_class_weight
from statsmodels.graphics.tsaplots import plot_acf, plot_pacf
from statsmodels.tsa.ar_model import AR, AutoReg

# from statsmodels.tsa.arima_model import ARIMA
from statsmodels.tsa.arima.model import ARIMA
from tabulate import tabulate
from tensorflow.keras.callbacks import EarlyStopping
from tensorflow.keras.layers import (
    GRU,
    LSTM,
    Bidirectional,
    Conv1D,
    Dense,
    Dropout,
    Flatten,
    MaxPooling1D,
    TimeDistributed,
)
from tensorflow.keras.layers import LSTM as KerasLSTM
from tensorflow.keras.models import Sequential
from tensorflow.keras.utils import to_categorical
from utils.data_fetcher import getDataFrame
