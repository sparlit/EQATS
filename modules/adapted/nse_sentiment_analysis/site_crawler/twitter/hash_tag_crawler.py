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


import csv

import pandas as pd
import tweepy
from site_crawler.cleaner.cleaner import Cleaner
from site_crawler.twitter.credentials import Credentials
from sklearn.externals import joblib

model = joblib.load("model.pkl")

credentials = Credentials()
cleaner = Cleaner()
api = credentials.authentinticate_twitter()


def predict(text2):

    from sklearn.externals import joblib

    model = joblib.load("model.pkl")

    prediction = model.predict(text2)

    return prediction[0]


text2 = [
    "the world's smallest disneyland has posted losses for 9 of the 12 years since it opened. local visitors make up 41%… ",
    "kenya's economy struggles",
    "loss making venture",
    "Uchumi",
    "nakumatt",
    "Centum ",
    "use becomes a public limited company",
]


query = "safaricom"
max_tweets = 10


searched_tweets = list(tweepy.Cursor(api.search, q=query).items(max_tweets))


outtweets = [
    [cleaner.clean_tweets(tweet.text), predict([cleaner.clean_tweets(tweet.text)])] for tweet in searched_tweets
]


# print(outtweets)
#
# exit()

# for tweets in outtweets:
#     print([tweets])

with open("./predict.csv", "w") as f:
    writer = csv.writer(f)
    writer.writerow(["text", "label"])
    writer.writerows(outtweets)

# df=pd.read_csv("./predict.csv")
# df=df.dropna(how='any')
# df=df.drop_duplicates()
# model=joblib.load("model.pkl")
# print(df.text)
# df['label'] = model.predict(df.text)
# print(df.label)
# df.to_csv("predicted.csv",encoding="utf8")
# #print(model.predict(df.text))
# print("read")
