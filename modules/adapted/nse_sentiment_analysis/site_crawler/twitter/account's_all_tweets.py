
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


import csv
import simplejson
from site_crawler.twitter.credentials import Credentials
from site_crawler.cleaner.cleaner import Cleaner

class Account_All_Tweets:
    def __init__(self):
        credentials = Credentials()
        self.cleaner = Cleaner()
        self.api = credentials.authentinticate_twitter()

    def get_all_tweets(self,profile_name):
            # Twitter only allows access to a users most recent 3240 tweets with this method
            # initialize a list to hold all the tweepy Tweets
            alltweets = []
            # make initial request for most recent tweets (200 is the maximum allowed count)
            new_tweets = self.api.user_timeline(screen_name=profile_name, count=200)
            # save most recent tweets
            alltweets.extend(new_tweets)
            # save the id of the oldest tweet less one
            oldest = alltweets[-1].id - 1
            # keep grabbing tweets until there are no tweets left to grab
            while len(new_tweets) > 0:
                # print("getting tweets before %s") % (oldest)
                # all subsiquent requests use the max_id param to prevent duplicates
                new_tweets = self.api.user_timeline(screen_name=profile_name, count=200, max_id=oldest)
                # save most recent tweets
                alltweets.extend(new_tweets)
                # update the id of the oldest tweet less one
                oldest = alltweets[-1].id - 1
                print("...%s tweets downloaded so far" % (len(alltweets)))
            # transform the tweepy tweets into a 2D array that will populate the csv
            outtweets = [[tweet.id_str, tweet.created_at, self.cleaner.pre_cleaning(tweet.text)] for tweet in alltweets]
            # write the csv
            with open('../data/twitter_data/raw_data/'+profile_name+'.csv', 'w') as f:
                writer = csv.writer(f)
                writer.writerow(["id", "created_at", "text","label"])
                writer.writerows(outtweets)
            pass

if __name__ == "__main__":
    account_tweets = Account_All_Tweets()
    twitter_handles = [
        'Business_KE',
        'MadeItInAfrica',
        'IFCAfrica',
        'africareview',
        'AfDB_Group',
        '_AfricanUnion',
        'Taifa_Leo',
        'BD_Africa',
        'RadioCitizenFM',
        'citizentvkenya',
        'KTNKenya',
        'K24Tv',
        'StandardKenya',
        'TheStarKenya',
        'radiomaisha',
        'KBCChannel1',
        'CapitalFMKenya',
        'African_Markets',
        'Africafinancial',
        'InvestInAfrica',
        'AfricanInvestor',
        'forbesafrica',
        'cnbcafrica',
        'BBCAfrica',
        'CNNAfrica',
        'allafrica',
        'ReutersAfrica',
        'VenturesAfrica',
        'BBGAfrica',
        'GhettoRadio895',
        'kenyanwalstreet',
        'SokoAnalyst',
        'NSEKenya',
        'wazua'
    ]

    for twitter_handle in twitter_handles:
        account_tweets.get_all_tweets(twitter_handle)