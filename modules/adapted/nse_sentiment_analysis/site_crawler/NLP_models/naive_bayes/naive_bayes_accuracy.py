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


import matplotlib.pyplot as plt
import pandas as pd
from sklearn import metrics
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
from sklearn.metrics import auc, roc_curve
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline


def readcsv():
    df = pd.read_csv(
        "../../data/dataset/csv/dataset_sentiment.csv",
    )  # read labelled tweets
    X = df.text
    y = df.label
    return X, y


def drawrocNB(y_test, y_pred):
    fpr, tpr, threshold = roc_curve(y_test, y_pred)
    print("Drawing")
    roc_auc = auc(fpr, tpr)
    plt.title("Receiver Operating Characteristic")
    plt.plot(fpr, tpr, "b", label=f"NB AUC = {roc_auc:0.2f}", color="r")
    plt.legend(loc="lower right")
    plt.plot([0, 1], [0, 1], "r--")
    plt.xlim([-0.1, 1.2])
    plt.ylim([-0.1, 1.2])
    plt.ylabel("True Positive Rate")
    plt.xlabel("False Positive Rate")
    plt.show()


def naive_bayes_accuraccy(X, y):
    """Different Classifiers"""
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=1)
    nb = Pipeline(
        [("vect", CountVectorizer()), ("tfidf", TfidfTransformer()), ("nb", MultinomialNB())]
    )
    nb = nb.fit(X_train, y_train)
    yprednb = nb.predict(X_test)
    print("Naive Bayes ")
    print(metrics.accuracy_score(y_test, yprednb))
    print(metrics.classification_report(y_test, yprednb))
    drawrocNB(y_test, yprednb)


def main():
    X, y = readcsv()
    naive_bayes_accuraccy(X, y)


if __name__ == "__main__":
    main()
