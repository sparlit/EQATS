
import datetime
import pytz

def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone('Asia/Kolkata')
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


#!/bin/python

import quandl
import pandas as pd
import numpy as np
import datetime

from sklearn.linear_model import LinearRegression
from sklearn import preprocessing, cross_validation, svm

df = quandl.get("WIKI/AMZN")

print 'dataframe'
print(df.tail(60))

df = df[['Adj. Close']]

print 'dataframe : only Adj.close'
print(df.tail(60))

forecast_out = int(30) # predicting 30 days into future

#  label column with data shifted 30 units up
df['Prediction'] = df[['Adj. Close']].shift(-forecast_out) 

print 'dataframe : with prediction label'
print(df)

# It should be same as
# drop (index or column, 0-index | 1-column))
# X = np.array(df.drop(['Prediction'], 1))
X = np.array(df[['Adj. Close']])

# print 'X : np array after dropping prediction'
print 'X : np array of Adj. Close'
print X

X = preprocessing.scale(X)

print 'X : after preprocessing scale'
print X

X = X[:-forecast_out] # remove last 30 from X

print 'X : remove last 30 from forecast'
print X

y = np.array(df['Prediction'])

print 'y : np array of dataframe prediction'
print y

y = y[:-forecast_out]

print 'y : remove last 30 days from y for forecst'
print y

print 'splited training and testing : data : cross_validation.train_test_split '
X_train, X_test, y_train, y_test = cross_validation.train_test_split(X, y, test_size = 0.2)

print 'X_train'
print X_train

print 'y_train'
print y_train

print 'X_test'
print X_test

print 'y_test'
print y_test

# Training : clf  - confidence level functionreplaced by model
model = LinearRegression()
model.fit(X_train,y_train)

# Testing
confidence = model.score(X_test, y_test)
print("confidence: ", confidence)

X_forecast = X[-forecast_out:] # set X_forecast equal to last 30

print 'X : forecast to last 30'
print X

forecast_prediction = model.predict(X_forecast)
print(forecast_prediction)
