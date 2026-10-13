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
import numpy as np
import pandas as pd
from sklearn import metrics
from sklearn.externals import joblib
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
from sklearn.metrics import auc, classification_report, roc_curve
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.svm import SVC


def shufflecsv():
    df = pd.read_csv("../../data/dataset/csv/dataset_sentiment.csv")
    df2 = df.reindex(np.random.permutation(df.index))
    df2.to_csv("final.csv", encoding="utf8")
    print("done shuffling")


def readcsv():
    df = pd.read_csv("final.csv")  # read labelled tweets
    # df2=df.reindex(np.random.permutation(df.index))
    X = df.text
    y = df.label
    return X, y


def drawrocSVM(y_test, y_pred):
    fpr, tpr, threshold = roc_curve(y_test, y_pred)
    print("Drawing")
    roc_auc = auc(fpr, tpr)
    plt.title("Receiver Operating Characteristic")
    plt.plot(fpr, tpr, "b", label=f"SVM AUC = {roc_auc:0.2f}", color="b")
    plt.legend(loc="lower right")
    plt.plot([0, 1], [0, 1], "r--")
    plt.xlim([-0.1, 1.2])
    plt.ylim([-0.1, 1.2])
    plt.ylabel("True Positive Rate")
    plt.xlabel("False Positive Rate")
    plt.show()


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


def drawrocKNN(y_test, y_pred):
    fpr, tpr, threshold = roc_curve(y_test, y_pred)
    print("Drawing")
    roc_auc = auc(fpr, tpr)
    plt.title("Receiver Operating Characteristic")
    plt.plot(fpr, tpr, "b", label=f"KNN AUC = {roc_auc:0.2f}", color="g")
    plt.legend(loc="lower right")
    plt.plot([0, 1], [0, 1], "r--")
    plt.xlim([-0.1, 1.2])
    plt.ylim([-0.1, 1.2])
    plt.ylabel("True Positive Rate")
    plt.xlabel("False Positive Rate")
    plt.show()


def savemodel(clf):
    joblib.dump(clf, "model.pkl")  # persisting the model


def createSVM(X, y):
    svm_clf = Pipeline(
        [
            ("vect", CountVectorizer(ngram_range=(1, 2))),
            ("tfidf", TfidfTransformer()),
            ("svm", SVC(kernel="linear", C=1)),
        ]
    )
    svm_clf = svm_clf.fit(X, y)
    return svm_clf


def createNB(X, y):
    nb_clf = Pipeline(
        [("vect", CountVectorizer()), ("tfidf", TfidfTransformer()), ("nb", MultinomialNB())]
    )
    nb_clf = nb_clf.fit(X, y)
    return nb_clf


def evaluatemodel(y_pred, y_test):
    print(metrics.confusion_matrix(y_test, y_pred))
    accuracy = metrics.accuracy_score(y_test, y_pred)
    print(accuracy)
    report = classification_report(y_test, y_pred)
    print(report)


def main():
    shufflecsv()
    X, y = readcsv()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.4, random_state=1
    )  # split data into training and testing sets

    svm_clf = createSVM(X_train, y_train)
    y_pred = svm_clf.predict(X_test)

    print("SVM evaluation")
    evaluatemodel(y_pred, y_test)
    drawrocSVM(y_test, y_pred)

    savemodel(svm_clf)


if __name__ == "__main__":
    main()
