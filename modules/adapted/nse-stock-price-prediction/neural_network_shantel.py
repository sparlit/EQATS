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
from sklearn import cross_validation, metrics
from sklearn.externals import joblib
from sklearn.neural_network import MLPClassifier
from sklearn.utils import shuffle

# df = pd.read_csv('shantel.csv')
df = pd.read_csv("labeled_shantel.csv")

df = shuffle(df)

array = df.values
X = array[:, 0:6]
Y = array[:, 6]


X_train, X_test, y_train, y_test = cross_validation.train_test_split(X, Y, test_size=0.3)

# Training
clf = MLPClassifier()
clf.fit(X_train, y_train)


# Testing
confidence = clf.score(X_test, y_test)
print("confidence: ", confidence)

ypred = clf.predict(X_test)
print(metrics.accuracy_score(y_test, ypred))
print(metrics.confusion_matrix(y_test, ypred))
print(metrics.classification_report(y_test, ypred))
# print(clf.predict([[17,29,23,40,94,69]]))
# print(clf.predict([[19,48,26,17,95,63]]))
# print(clf.predict([[19,14,10,25,62,41]]))

joblib.dump(clf, "model.pkl")


#
# print(clf.predict([[17,	29,	23,	26,	95,	67]]))
# print(clf.predict([[18,	30,	23,	38,	95,	67]]))
# print(clf.predict([[18,	30,	23,	35,	97,	68]]))
# print(clf.predict([[15,	33,	24,	23,	94,	23]]))
# print(clf.predict([[18,	30,	24,	34,	95,	68]]))
# print(clf.predict([[14,	32,	25,	28,	90,	61]]))
# print(clf.predict([[19,	30,	24,	34,	89,	61]]))
# print(clf.predict([[21,	35,	27,	14,	85,	48]]))
# print(clf.predict([[17,	30,	23,43,100,75]]))


# forecast_prediction = clf.predict(X_forecast)
# print(forecast_prediction)
