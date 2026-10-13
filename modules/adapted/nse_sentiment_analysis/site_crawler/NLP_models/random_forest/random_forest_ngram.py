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
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline


def readcsv():
    df = pd.read_csv(
        "../../data/dataset/csv/dataset_sentiment.csv",
    )
    X = df.text
    y = df.label
    return X, y


def createRandomForest(X, y):
    svm_clf = Pipeline(
        [
            ("vect", CountVectorizer()),
            ("tfidf", TfidfTransformer()),
            ("RFC", RandomForestClassifier(kernel="linear", C=1)),
        ]
    )
    svm_clf = svm_clf.fit(X, y)
    return svm_clf


def svm_ngram(X, y):
    """Different features with SVM"""
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=0)
    svm = createRandomForest(X_train, y_train)
    y_pred = svm.predict(X_test)
    print("Original Accuracy: Unigram with tf-idf")
    print(metrics.confusion_matrix(y_test, y_pred))
    print(metrics.accuracy_score(y_test, y_pred))
    print(metrics.classification_report(y_test, y_pred))
    svm2 = Pipeline(
        [("vect", CountVectorizer()), ("svm", RandomForestClassifier(kernel="linear", C=1))]
    )
    svm2 = svm2.fit(X_train, y_train)
    ypred2 = svm2.predict(X_test)
    print("Just unigram counts Accuracy")
    print(metrics.accuracy_score(y_test, ypred2))
    print(metrics.classification_report(y_test, ypred2))
    svm3 = Pipeline(
        [
            ("vect", CountVectorizer(ngram_range=(1, 2))),
            ("svm", RandomForestClassifier(kernel="linear", C=1)),
        ]
    )
    svm3 = svm3.fit(X_train, y_train)
    ypred3 = svm3.predict(X_test)
    print("just bigram counts Accuracy")
    print(metrics.accuracy_score(y_test, ypred3))
    print(metrics.classification_report(y_test, ypred3))
    svm4 = Pipeline(
        [
            ("vect", CountVectorizer(ngram_range=(1, 3))),
            ("svm", RandomForestClassifier(kernel="linear", C=1)),
        ]
    )
    svm4 = svm4.fit(X_train, y_train)
    ypred4 = svm4.predict(X_test)
    print("Trigram counts Accuracy")
    print(metrics.accuracy_score(y_test, ypred4))
    print(metrics.classification_report(y_test, ypred4))
    svm5 = Pipeline(
        [
            ("vect", CountVectorizer(ngram_range=(1, 2))),
            ("tfidf", TfidfTransformer()),
            ("svm", RandomForestClassifier(kernel="linear", C=1)),
        ]
    )
    svm5 = svm5.fit(X_train, y_train)
    ypred5 = svm5.predict(X_test)
    print("bigram with tfidf Accuracy")
    # print(metrics.confusion_matrix(y_test,ypred5))
    print(metrics.accuracy_score(y_test, ypred5))
    print(metrics.classification_report(y_test, ypred5))
    svm6 = Pipeline(
        [
            ("vect", CountVectorizer(ngram_range=(1, 3))),
            ("tfidf", TfidfTransformer()),
            ("svm", RandomForestClassifier(kernel="linear", C=1)),
        ]
    )
    svm6 = svm6.fit(X_train, y_train)
    ypred6 = svm6.predict(X_test)
    print("trigram with tfidf Accuracy")
    # print(metrics.confusion_matrix(y_test,ypred6))
    print(metrics.accuracy_score(y_test, ypred6))
    print(metrics.classification_report(y_test, ypred6))


def main():
    X, y = readcsv()
    svm_ngram(X, y)


if __name__ == "__main__":
    main()
