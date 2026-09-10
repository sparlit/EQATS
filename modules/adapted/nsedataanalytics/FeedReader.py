
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


#Import the necessary methods from tweepy library
from tweepy.streaming import StreamListener
from tweepy import OAuthHandler
from tweepy import Stream
import json
#Variables that contains the user credentials to access Twitter API 
access_token = "782730432-K7m6BlGBmWxRNhDBxO7WDXkGIE3N7vitnMwmQrT4"
access_token_secret = "mN565FUoXQffNRPyf3meErRNoF8isyAkBsBnxQMDKFz1Y"
consumer_key = "oxya7KmlE7yhLlS3m3Yc7BHEP"
consumer_secret = "Uc3E8STnjQ1jEatJTqexistZn5ZHqXPajAi18Hu0Jwg529eBoR"


#This is a basic listener that just prints received tweets to stdout.
class StdOutListener(StreamListener):

    def on_data(self, data):
        tweet=json.loads(data)
        try:
             with open('fetched_tweets.txt','a') as tf:
                 tf.write(tweet['text'].encode('utf-8'))
                 tf.write('\n')
        except KeyError:
            pass
        
        return True

    def on_error(self, status):
        print status


if __name__ == '__main__':

    #This handles Twitter authetification and the connection to Twitter Streaming API
    l = StdOutListener()
    auth = OAuthHandler(consumer_key, consumer_secret)
    auth.set_access_token(access_token, access_token_secret)
    stream = Stream(auth, l)
    #stream.userstream(_with='followings')
    
    #This line filter Twitter Streams to capture data by the keywords: 'python', 'javascript', 'ruby'
    stream.filter(follow=['81083096','68927629'])