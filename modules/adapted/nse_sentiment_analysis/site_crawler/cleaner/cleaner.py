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
import html
import re
import string


class Cleaner:
    def __init__(self):
        self.remove_punctuations = str.maketrans("", "", string.punctuation)

    def read_csv(self, csv_name):
        cleaned_text = []
        with open(
            "../data/twitter_data/raw_data/" + csv_name + ".csv", newline="", encoding="utf-8"
        ) as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                text = row["text"]
                clean_text = self.clean_tweets(text)
                cleaned_text.append(clean_text)
        self.save_cleaned_csv("cleaned_" + csv_name, cleaned_text)

    def clean_tweets(self, tweet):
        # harmonize the cases
        lower_case_text = tweet.lower()
        # remove urls
        removed_url = re.sub(r"http\S+", "", lower_case_text)
        # remove hashtags
        removed_hash_tag = re.sub(r"#\w*", "", removed_url)  # hastag
        # remove usernames from tweets
        removed_username = re.sub(r"@\w*\s?", "", removed_hash_tag)
        # removed retweets
        removed_retweet = removed_username.replace("rt", "", True)  # remove to retweet
        # removing punctuations
        removed_punctuation = removed_retweet.translate(self.remove_punctuations)
        # remove spaces
        remove_g_t = removed_punctuation.replace("&gt", "", True)
        remove_a_m_p = remove_g_t.replace("&amp", "", True)
        final_text = remove_a_m_p
        return final_text

    def pre_cleaning(self, text):
        html_escaped = html.unescape(text)
        final_text = html_escaped.replace(";", "")
        return final_text

    def pre_labeling(self, text):
        lower_case_text = text.lower()
        removed_url = re.sub(r"http\S+", "", lower_case_text)
        return removed_url

    def save_cleaned_csv(self, name, tweets_list):
        with open("../data/twitter_data/cleaned_data/" + name + ".csv", "w") as f:
            writer = csv.writer(f)
            writer.writerow(["text"])
            for tweet in tweets_list:
                writer.writerow(
                    [
                        tweet,
                    ]
                )
        pass

    def save_pre_labled_csv(self, csv_name):
        cleaned_text = []
        with open(
            "../data/twitter_data/raw_data/" + csv_name + ".csv", newline="", encoding="utf-8"
        ) as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                text = row["text"]
                clean_text = self.pre_labeling(text)
                cleaned_text.append(clean_text)
        self.save_pre_labeled_csv("unlabeled_" + csv_name, cleaned_text)

    def save_pre_labeled_csv(self, name, tweets_list):
        with open("../data/twitter_data/pre_labeled/" + name + ".csv", "w") as f:
            writer = csv.writer(f)
            writer.writerow(["text", "label"])
            for tweet in tweets_list:
                writer.writerow(
                    [
                        tweet,
                    ]
                )
        pass


if __name__ == "__main__":
    c = Cleaner()
    tweets_csvs = [
        "Business_KE",
        "MadeItInAfrica",
        "IFCAfrica",
        "africareview",
        "AfDB_Group",
        "_AfricanUnion",
        "Taifa_Leo",
        "BD_Africa",
        "RadioCitizenFM",
        "citizentvkenya",
        "KTNKenya",
        "K24Tv",
        "StandardKenya",
        "TheStarKenya",
        "radiomaisha",
        "KBCChannel1",
        "CapitalFMKenya",
        "African_Markets",
        "Africafinancial",
        "InvestInAfrica",
        "AfricanInvestor",
        "forbesafrica",
        "cnbcafrica",
        "BBCAfrica",
        "CNNAfrica",
        "allafrica",
        "ReutersAfrica",
        "VenturesAfrica",
        "BBGAfrica",
        "GhettoRadio895",
        "kenyanwalstreet",
        "SokoAnalyst",
        "NSEKenya",
        "wazua",
    ]

    for tweets_csv in tweets_csvs:
        c.save_pre_labled_csv(tweets_csv)
