import datetime
from typing import Optional

import pytz

try:
    import streamlit as st
except ImportError:
    st = None

try:
    from PIL import Image
except ImportError:
    Image = None

try:
    import keras.backend.tensorflow_backend as tb

    tb._SYMBOLIC_SCOPE.value = True
except ImportError:
    pass


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


def main() -> None:
    if st is None:
        msg = "streamlit is required to run this application"
        raise RuntimeError(msg)
    if Image is None:
        msg = "PIL is required to run this application"
        raise RuntimeError(msg)

    image = Image.open("sm.jpeg")
    st.image(image, use_column_width=True)

    st.title("NSE Real-Time Stocks Analysis and Predictions")

    st.header("Select the stock and check its next day predicted value")

    st.subheader(
        "This study is mainly confined to the stock market behavior and is "
        "intended to devise certain techniques for investors to make reasonable "
        "returns from investments."
    )

    st.subheader(
        "Though there were a number of studies, which "
        "deal with analysis of stock price behaviours, the use of control chart "
        "techniques and failure time analysis would be new to the investors. The "
        "concept of stock price elasticity, "
        "introduced in this study, will be a good "
        "tool to measure the sensitivity of stock price movements."
    )

    st.subheader(
        "In this study, "
        "Predictions for the close price is suggested for the National Stock Exchange index, "
        "Nifty, "
        "based on Long Short Term Based (LSTM) "
        "method."
    )

    st.subheader(
        "We make predictions based on the last 30 days Closing price data "
        "which we fetch from NSE India website in realtime."
    )

    st.markdown(
        "Note: This is just a fun project, No one can predict the "
        "stock market as of today because there are a "
        "lot of factors which needs to be considered "
        "before making any investments, especially in StockMarket. "
        "So it is advisable not to indulge in any "
        "bad decisions based on the predictions shown here."
    )

    st.header("THANKS FOLKS!!")

    st.subheader("Happy Learning")

    st.subheader("Creator: MRINAL WALIA")

    st.header(
        "Article Link: https://datascienceplus.com/real-time-national-stock-exchange-nse-of-india-close-price-stocks-predictions-in-python/"
    )
    st.header("Source Code Link: https://github.com")


if __name__ == "__main__":
    main()
