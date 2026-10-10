
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


#!/usr/bin/python -tt

import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import scipy.optimize as spo


def main():
    print "Start"
    dfINFY = pd.read_csv("XNSE-INFY.csv", index_col='Date')
    # print dfINFY
    # print dfINFY.ix['2011-12-30':'2011-12-27'] #row slice

    dfINFY.ix['2012-09-24':'2011-12-27', ['High', 'Low']].plot()  # row-column slice
    plt.show()


def plot_selected(df, columns, start_index, end_index):
    """Plot the desired columns over index values in the given range."""
    # Note: DO NOT modify anything else!
    # print df
    newDF = df.ix[start_index:end_index, columns]
    plot_data(newDF)


def symbol_to_path(symbol, base_dir=""):
    """Return CSV file path given ticker symbol."""
    # return os.path.join(base_dir, "{}.csv".format(str(symbol)))
    return "{}.csv".format(str(symbol))


def get_data(symbols, dates):
    # """Read stock data (adjusted close) for given symbols from CSV files."""
    df = pd.DataFrame(index=dates)
    # if 'SPY' not in symbols:  # add SPY for reference, if absent
    #     symbols.insert(0, 'SPY')

    for symbol in symbols:
        df_temp = pd.read_csv(symbol_to_path(symbol), index_col='Date',
                              parse_dates=True, usecols=['Date', 'Adj Close'], na_values=['nan'])
        df_temp = df_temp.rename(columns={'Adj Close': symbol})
        df = df.join(df_temp)
        # if symbol == 'INFY':  # drop dates SPY did not trade
        #     df = df.dropna(subset=["INFY"])
        df = df.dropna()
    return df


def compute_daily_returns(df):
    """Compute and return the daily return values."""
    # Note: Returned DataFrame must have the same number of rows
    daily_returns = (df / df.shift(1)) - 1
    daily_returns.ix[0, :] = 0
    return daily_returns


def plot_hist_on_daily_returns(df):
    df = compute_daily_returns(df)
    mean_INFY = df['INFY'].mean()
    std_INFY = df['INFY'].std()
    print mean_INFY
    print std_INFY
    df['INFY'].hist(bins=50)
    df['TCS'].hist(bins=50)
    plt.axvline(mean_INFY)
    plt.axvline(std_INFY)
    plt.axvline(-std_INFY)
    plt.show()


def plot_scatter(df):
    df.plot(kind='scatter', x='INFY', y='TCS')
    plt.show()


def plot_data(df, title="Stock prices"):
    """Plot stock prices with a custom title and meaningful axis labels."""
    ax = df.plot(title=title, fontsize=12)
    ax.set_xlabel("Date")
    ax.set_ylabel("Price")
    plt.show()


def normalize_df(df):
    return df / df.ix[0, :]


def test_run():
    # Define a date range
    dates = pd.date_range('2017-01-02', '2017-09-22')

    # Choose stock symbols to read
    symbols = ['INFY', 'TCS']

    # Get stock data
    df = get_data(symbols, dates)

    # Fill missing data...
    df.fillna(method="ffill", inplace=True)
    df.fillna(method="bfill", inplace=True)

    # df = normalize_df(df)
    # Slice and plot
    # plot_selected(df, symbols, '2017-01-02', '2017-09-22')
    # plot_hist_on_daily_returns(df)
    plot_scatter(df)


if __name__ == '__main__':
    test_run()