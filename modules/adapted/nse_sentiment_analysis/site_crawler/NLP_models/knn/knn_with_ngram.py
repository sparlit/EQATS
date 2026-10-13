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


import pandas as pd
from sklearn import metrics
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline


def readcsv():
    df = pd.read_csv(
        "../../data/dataset/csv/dataset_sentiment.csv",
    )
    X = df.text
    y = df.label
    return X, y


def knn_ngram(X, y):
    """Different feature sets with KNN"""
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=0)
    knn = Pipeline(
        [
            ("vect", CountVectorizer()),
            ("tfidf", TfidfTransformer()),
            ("knn", KNeighborsClassifier()),
        ]
    )
    knn = knn.fit(X_train, y_train)
    ypredknn = knn.predict(X_test)
    print("Original Accuracy: Unigram tfidf")
    print(metrics.accuracy_score(y_test, ypredknn))
    print(metrics.classification_report(y_test, ypredknn))
    knn = Pipeline([("vect", CountVectorizer()), ("knn", KNeighborsClassifier())])
    knn = knn.fit(X_train, y_train)
    ypredknn = knn.predict(X_test)
    print("Unigram counts")
    print(metrics.accuracy_score(y_test, ypredknn))
    print(metrics.classification_report(y_test, ypredknn))
    knn = Pipeline([("vect", CountVectorizer(ngram_range=(1, 2))), ("knn", KNeighborsClassifier())])
    knn = knn.fit(X_train, y_train)
    ypredknn = knn.predict(X_test)
    print("Bigram counts")
    print(metrics.accuracy_score(y_test, ypredknn))
    print(metrics.classification_report(y_test, ypredknn))
    knn = Pipeline(
        [
            ("vect", CountVectorizer(ngram_range=(1, 2))),
            ("tfidf", TfidfTransformer()),
            ("knn", KNeighborsClassifier()),
        ]
    )
    knn = knn.fit(X_train, y_train)
    ypredknn = knn.predict(X_test)
    print("Bigram tfidf")
    print(metrics.accuracy_score(y_test, ypredknn))
    print(metrics.classification_report(y_test, ypredknn))
    knn = Pipeline([("vect", CountVectorizer(ngram_range=(1, 3))), ("knn", KNeighborsClassifier())])
    knn = knn.fit(X_train, y_train)
    ypredknn = knn.predict(X_test)
    print("trigram counts")
    print(metrics.accuracy_score(y_test, ypredknn))
    print(metrics.classification_report(y_test, ypredknn))
    knn = Pipeline(
        [
            ("vect", CountVectorizer(ngram_range=(1, 3))),
            ("tfidf", TfidfTransformer()),
            ("knn", KNeighborsClassifier()),
        ]
    )
    knn = knn.fit(X_train, y_train)
    ypredknn = knn.predict(X_test)
    print("Trigram tfidf")
    print(metrics.accuracy_score(y_test, ypredknn))
    print(metrics.classification_report(y_test, ypredknn))


def main():
    X, y = readcsv()
    knn_ngram(X, y)


if __name__ == "__main__":
    main()
