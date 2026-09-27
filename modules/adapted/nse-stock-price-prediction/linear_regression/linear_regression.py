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


import numpy as np
import pandas as pd
from sklearn import cross_validation, preprocessing
from sklearn.linear_model import LinearRegression

df = pd.read_csv("../equity.csv")

# print(df[[3]])
#
# exit()

df_close = df[[3]]

forecast_out = 30  # predicting 30 days into future


df["Prediction"] = df_close.shift(-forecast_out)  #  label column with data shifted 30 units up

# print(df.tail())

X = np.array(df.drop(["Prediction"], 1))
X = preprocessing.scale(X)


X_forecast = X[-forecast_out:]  # set X_forecast equal to last 30
X = X[:-forecast_out]  # remove last 30 from X


y = np.array(df["Prediction"])
y = y[:-forecast_out]


X_train, X_test, y_train, y_test = cross_validation.train_test_split(X, y, test_size=0.3)

# Training
clf = LinearRegression()
clf.fit(X_train, y_train)
# Testing
confidence = clf.score(X_test, y_test)
print("confidence: ", confidence)


forecast_prediction = clf.predict(X_forecast)
print(forecast_prediction)
