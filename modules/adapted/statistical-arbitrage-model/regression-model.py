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


# -*- coding: utf-8 -*-
"""
Created on Thu Dec 20 20:49:06 2018

@author: HARSHA
"""

from datetime import datetime

# to plot within notebook
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import style

style.use("ggplot")
##%matplotlib inline

# setting figure size
from matplotlib.pylab import rcParams

rcParams["figure.figsize"] = 20, 10

# for normalizing data
from sklearn.preprocessing import MinMaxScaler

scaler = MinMaxScaler(feature_range=(0, 1))
from mlxtend.plotting import plot_decision_regions
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LinearRegression, RANSACRegressor, TheilSenRegressor
from sklearn.metrics import precision_score, recall_score
from sklearn.model_selection import train_test_split

# Reading Data
stocks = pd.read_csv("20microns.csv")
print(stocks.head())

# Time Series Analysis
start16 = datetime(2016, 1, 1)
end16 = datetime(2016, 12, 31)
stamp16 = pd.date_range(start16, end16)

start17 = datetime(2017, 1, 1)
end17 = datetime(2017, 12, 31)
stamp17 = pd.date_range(start17, end17)

stocks["Date"] = pd.to_datetime(stocks.TIMESTAMP, format="%Y-%m-%d")
stocks.index = stocks["Date"]

# New Dataset
stocks = stocks[["OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY", "Date", "PREVCLOSE", "TOTTRDVAL", "TOTALTRADES"]]
stocks["HL_PCT"] = (stocks["HIGH"] - stocks["LOW"]) / stocks["LOW"] * 100.0
stocks.index = stocks["Date"]

# Seperating Train and test data
train = []
test = []
for index, rows in stocks.iterrows():
    if index in stamp16:
        train.append(list(rows))
    if index in stamp17:
        test.append(list(rows))

train = pd.DataFrame(train, columns=stocks.columns)
test = pd.DataFrame(test, columns=stocks.columns)


# print(train.head())
# print(test.head())


# Pre-Processing  Train Data
X_train = train[["HIGH", "LOW", "OPEN", "TOTTRDQTY", "TOTTRDVAL", "TOTALTRADES"]]
x_train = X_train.to_dict(orient="records")
vec = DictVectorizer()
X = vec.fit_transform(x_train).toarray()
Y = np.asarray(train.CLOSE)
Y = Y.astype("int")

# Pre-Processing Test data
X_test = test[["HIGH", "LOW", "OPEN", "TOTTRDQTY", "TOTTRDVAL", "TOTALTRADES"]]
x_test = X_test.to_dict(orient="records")
vec = DictVectorizer()
x = vec.fit_transform(x_test).toarray()
y = np.asarray(test.CLOSE)
y = y.astype("int")


# Classifier
clf = TheilSenRegressor()
clf.fit(X, Y)
print("Accuracy of this Statistical Arbitrage model is: ", clf.score(x, y))
predict = clf.predict(x)

test["predict"] = predict

# Ploting
train.index = train.Date
test.index = test.Date
train["CLOSE"].plot()
test["CLOSE"].plot()
test["predict"].plot()
plt.legend(loc="best")
plt.xlabel("Date")
plt.ylabel("Price")
plt.show()
