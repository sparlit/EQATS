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


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Mar 18 06:41:34 2018

@author: sahiljajodia
"""

import numpy as np
import requests
import tweepy
from keras.layers import Dense
from keras.models import Sequential
from textblob import TextBlob

consumer_key = "K8rDGMdTDwKz2tWpNIuurZSr7"
consumer_secret = "wb1ZWvuC9loX78f6GVDVgNzoG0YATKLhPwjtXlnWrOiplm901u"
access_token = "962553243116204032-XWr3Ud2mD56izQFWFXu2aZMCZ9MkGxZ"
access_token_secret = "fqYgYnEAkwy15NZBHhjb0ZCoL67hybGZe7fni8QXFL2RY"
auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
auth.set_access_token(access_token, access_token_secret)
user = tweepy.API(auth)

# Where the csv file will live
data = "data.csv"


def stock_sentiment(quote, num_tweets):
    # Checks if the sentiment for our quote is
    # positive or negative, returns True if
    # majority of valid tweets have positive sentiment
    list_of_tweets = user.search(quote, count=num_tweets)
    positive, null = 0, 0

    for tweet in list_of_tweets:
        blob = TextBlob(tweet.text).sentiment
        if blob.subjectivity == 0:
            null += 1
            next
        if blob.polarity > 0:
            positive += 1

    if positive > ((num_tweets - null) / 2):
        return True


def get_data(stock):
    # Download our file from google finance
    url = "https://query1.finance.yahoo.com/v7/finance/download/QCOM?period1=1518920811&period2=1521340011&interval=1d&events=history&crumb=VGUdA6X.m5Q"
    r = requests.get(url, stream=True)

    if r.status_code != 400:
        with open(data, "wb") as f:
            for chunk in r:
                f.write(chunk)
        return True


def stock_prediction(stock):

    # Collect data points from csv
    dataset = []

    f = open("data.csv")

    for n, line in enumerate(f):
        if n != 0:
            dataset.append(float(line.split(",")[1]))

    dataset = np.array(dataset)

    # Create dataset matrix (X=t and Y=t+1)
    def create_dataset(dataset):
        dataX = [dataset[n + 1] for n in range(len(dataset) - 2)]
        return np.array(dataX), dataset[2:]

    trainX, trainY = create_dataset(dataset)

    # Create and fit Multilinear Perceptron model
    model = Sequential()
    model.add(Dense(8, input_dim=1, activation="relu"))
    model.add(Dense(1))
    model.compile(loss="mean_squared_error", optimizer="adam")
    model.fit(trainX, trainY, epochs=200, batch_size=2, verbose=0)

    # Our prediction for tomorrow
    prediction = model.predict(np.array([dataset[0]]))
    result = f"{stock}'s stock price will move from {dataset[0]} to {prediction[0][0]} on the next open day of the stock exchange."
    return result


# Ask user for a stock quote
stock = input("Enter a stock quote from NASDAQ (e.g: AAPL, FB, GOOGL): ").upper()

num_tweets = int(
    input(f"How many tweets should I look through to determine the sentiment about {stock}? ")
)

# get_data(stock)

import datetime
import re
import time


def split_crumb_store(v):
    return v.split(":")[2].strip('"')


def find_crumb_store(lines):
    # Looking for
    # ,"CrumbStore":{"crumb":"9q.A4D1c.b9
    for l in lines:
        if re.findall(r"CrumbStore", l):
            return l
    print("Did not find CrumbStore")


def get_cookie_value(r):
    return {"B": r.cookies["B"]}


def get_page_data(symbol):
    url = f"https://finance.yahoo.com/quote/{symbol}/?p={symbol}"
    r = requests.get(url)
    cookie = get_cookie_value(r)

    # Code to replace possible \u002F value
    # ,"CrumbStore":{"crumb":"FWP\u002F5EFll3U"
    # FWP\u002F5EFll3U
    lines = r.content.decode("unicode-escape").strip().replace("}", "\n")
    return cookie, lines.split("\n")


def get_cookie_crumb(symbol):
    cookie, lines = get_page_data(symbol)
    crumb = split_crumb_store(find_crumb_store(lines))
    return cookie, crumb


def get_data_quote(symbol, start_date, end_date, cookie, crumb):
    filename = "data.csv"
    url = f"https://query1.finance.yahoo.com/v7/finance/download/{symbol}?period1={start_date}&period2={end_date}&interval=1d&events=history&crumb={crumb}"
    response = requests.get(url, cookies=cookie)
    with open(filename, "wb") as handle:
        for block in response.iter_content(1024):
            handle.write(block)


def get_now_epoch():
    # @see https://www.linuxquestions.org/questions/programming-9/python-datetime-to-epoch-4175520007/#post5244109
    return int(time.time())


def download_quotes(symbol):
    start_date = 0
    end_date = get_now_epoch()
    cookie, crumb = get_cookie_crumb(symbol)
    get_data_quote(symbol, start_date, end_date, cookie, crumb)


download_quotes(stock)


if stock_sentiment(stock, num_tweets):
    print("This stock has good sentiment on Twitter.")

if not stock_sentiment(stock, num_tweets):
    print("This stock has bad sentiment on Twitter.")

# We have our file so we create the neural net and get the prediction
print(stock_prediction(stock))

# We are done so we delete the csv file
# Sos.remove(data)
