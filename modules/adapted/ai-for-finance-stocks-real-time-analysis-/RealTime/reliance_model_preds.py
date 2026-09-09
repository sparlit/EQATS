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


# Import the libraries
import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pandas_datareader as web
from keras.layers import LSTM, Dense
from keras.models import Sequential
from sklearn.preprocessing import MinMaxScaler

plt.style.use("fivethirtyeight")
from datetime import date

from nsepy import get_history

symbol = input("Enter symbol of stockn")
df = get_history(symbol=symbol, start=date(2010, 1, 1), end=date.today())
df["Date"] = df.index
df.tail()
df.shape
plt.figure(figsize=(16, 8))
# title for the plot
plt.title("Stocks Close Price Analysis")
# interactive area plot with matplotlib
plt.fill_between(df["Date"], df["Close"], color="skyblue", alpha=0.2)
plt.plot(df["Date"], df["Close"], color="skyblue", alpha=0.6)
# x-axis and y-axis labels
plt.xlabel("Time/Date", fontsize=18)
plt.ylabel("Stock Close Price", fontsize=18)
plt.show()
close_col = df.filter(["Close"])
close_col_val = close_col.values
# divide the dataset into training data(75%) and testing data(25%)
train_len = math.ceil(len(close_col_val) * 0.75)
mm_scale = MinMaxScaler(feature_range=(0, 1))
mm_scale_data = mm_scale.fit_transform(close_col_val)
train_data_val = mm_scale_data[0:train_len, :]
# Split the data
x_train = []
y_train = []
for i in range(30, len(train_data_val)):
    x_train.append(train_data_val[i - 30 : i, 0])
    y_train.append(train_data_val[i, 0])

x_train, y_train = np.array(x_train), np.array(y_train)
x_train = np.reshape(x_train, (x_train.shape[0], x_train.shape[1], 1))
from keras.layers import Dropout

network = Sequential()
# First layer
network.add(LSTM(units=50, return_sequences=True, input_shape=(x_train.shape[1], 1)))
network.add(Dropout(0.2))
# Second LSTM layer and dropout regularisation
network.add(LSTM(units=50, return_sequences=True))
network.add(Dropout(0.2))
# Third LSTM layer and dropout regularisation
network.add(LSTM(units=50, return_sequences=True))
network.add(Dropout(0.2))
# Fourth LSTM layer and dropout regularisation
network.add(LSTM(units=50))
network.add(Dropout(0.2))
# Output layer
network.add(Dense(units=1))

network.compile(optimizer="adam", loss="mean_squared_error")

network.fit(x_train, y_train, epochs=100, batch_size=50)
network.save(symbol + ".model")
test_data_val = mm_scale_data[train_len - 30 :, :]
x_test = []
y_test = close_col_val[train_len:, :]
for i in range(30, len(test_data_val)):
    x_test.append(test_data_val[i - 30 : i, 0])

x_test = np.array(x_test)
x_test = np.reshape(x_test, (x_test.shape[0], x_test.shape[1], 1))
preds = network.predict(x_test)
preds = mm_scale.inverse_transform(preds)  # Undo scaling
# calculate Root Mean Square Error Score error_score=np.sqrt(np.mean(((preds- y_test)**2)))
error_score
training_data = close_col[:train_len]
validation_data = close_col[train_len:]
validation_data["Preds"] = preds
plt.figure(figsize=(16, 8))
plt.title("LSTM Network Predicted Model")
plt.xlabel("Time/Date", fontsize=18)
plt.ylabel("Stock Close Price", fontsize=18)
plt.plot(training_data["Close"])
plt.plot(validation_data[["Close", "Preds"]])
plt.legend(["Training_values", "Validation_values", "Predictions_values"], loc="lower right")
plt.show()
new_close_col = df.filter(["Close"])
new_close_col_val = new_close_col[-30:].values
new_close_col_val_scale = mm_scale.transform(new_close_col_val)

X_test = []
X_test.append(new_close_col_val_scale)
X_test = np.array(X_test)
X_test = np.reshape(X_test, (X_test.shape[0], X_test.shape[1], 1))

new_preds = network.predict(X_test)
new_preds = mm_scale.inverse_transform(new_preds)
print(new_preds[0])
