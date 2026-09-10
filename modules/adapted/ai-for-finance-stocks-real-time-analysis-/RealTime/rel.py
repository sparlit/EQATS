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


import datetime
from datetime import date

import numpy as np
import pandas as pd
import streamlit as st
from keras.models import load_model
from nsepy import get_history
from PIL import Image
from sklearn.preprocessing import MinMaxScaler


def main():

    image = Image.open("sm.jpeg")
    st.image(image, use_column_width=True)

    st.title("NSE Real-Time Stocks Analysis and Predictions")

    st.header("Select the stock and check its next day predicted value")

    choose_stock = st.sidebar.selectbox("Choose the Stock!", ["NONE", "Reliance", "PowerMech Solns.", "RepcoHomes"])

    if choose_stock == "Reliance":
        # get abfrl real time stock price
        df1 = get_history(symbol="reliance", start=date(2010, 1, 1), end=date.today())
        df1["Date"] = df1.index

        st.header("Reliance India NSE Last 5 Days DataFrame:")

        # Insert Check-Box to show the snippet of the data.
        if st.checkbox("Show Raw Data"):
            st.subheader("Showing raw data---->>>")
            st.dataframe(df1.tail())

        ## Predictions and adding it to Dashboard
        new_close_col = df1.filter(["Close"])
        mm_scale = MinMaxScaler(feature_range=(0, 1))
        mm_scale.fit_transform(new_close_col)
        new_close_col_val = new_close_col[-30:].values
        new_close_col_val_scale = mm_scale.transform(new_close_col_val)

        X_test = []
        X_test.append(new_close_col_val_scale)
        X_test = np.array(X_test)
        X_test = np.reshape(X_test, (X_test.shape[0], X_test.shape[1], 1))
        network = load_model("reliance.model")
        new_preds = network.predict(X_test)
        new_preds = mm_scale.inverse_transform(new_preds)
        # print(new_preds[0])

        # next day
        NextDay_Date = datetime.date.today() + datetime.timedelta(days=1)

        st.subheader("Predictions for the next upcoming day Close Price : " + str(NextDay_Date))
        st.markdown(new_preds[0][0])

        st.subheader("Close Price VS Date Interactive chart for analysis:")
        st.area_chart(df1["Close"])

        st.subheader("Line chart of Open and Close for analysis:")
        st.area_chart(df1[["Open", "Close"]])

        st.subheader("Line chart of High and Low for analysis:")
        st.line_chart(df1[["High", "Low"]])


# driver code
if __name__ == "__main__":
    main()
