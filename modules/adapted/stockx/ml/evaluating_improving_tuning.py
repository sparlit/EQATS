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


# Artificial Neural Network

# Installing Theano
# pip install --upgrade --no-deps git+git://github.com/Theano/Theano.git

# Installing Tensorflow
# pip install tensorflow

# Installing Keras
# pip install --upgrade keras

# Part 1 - Data Preprocessing

# Importing the libraries
import numpy as np
import pandas as pd

# Importing the dataset
dataset = pd.read_csv("Churn_Modelling.csv")
X = dataset.iloc[:, 3:13].values
y = dataset.iloc[:, 13].values

# Encoding categorical data
from sklearn.preprocessing import LabelEncoder, OneHotEncoder

labelencoder_X_1 = LabelEncoder()
X[:, 1] = labelencoder_X_1.fit_transform(X[:, 1])
labelencoder_X_2 = LabelEncoder()
X[:, 2] = labelencoder_X_2.fit_transform(X[:, 2])
onehotencoder = OneHotEncoder(categorical_features=[1])
X = onehotencoder.fit_transform(X).toarray()
X = X[:, 1:]

# Splitting the dataset into the Training set and Test set
from sklearn.model_selection import train_test_split

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=0)

# Feature Scaling
from sklearn.preprocessing import StandardScaler

sc = StandardScaler()
X_train = sc.fit_transform(X_train)
X_test = sc.transform(X_test)

# Part 2 - Now let's make the ANN!

# Importing the Keras libraries and packages
from keras.layers import Dense
from keras.models import Sequential

# Initialising the ANN
classifier = Sequential()

# Adding the input layer and the first hidden layer
classifier.add(Dense(units=6, kernel_initializer="uniform", activation="relu", input_dim=11))
# classifier.add(Dropout(p = 0.1))

# Adding the second hidden layer
classifier.add(Dense(units=6, kernel_initializer="uniform", activation="relu"))
# classifier.add(Dropout(p = 0.1))

# Adding the output layer
classifier.add(Dense(units=1, kernel_initializer="uniform", activation="sigmoid"))

# Compiling the ANN
classifier.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])

# Fitting the ANN to the Training set
classifier.fit(X_train, y_train, batch_size=10, epochs=100)

# Part 3 - Making predictions and evaluating the model

# Predicting the Test set results
y_pred = classifier.predict(X_test)
y_pred = y_pred > 0.5

# Predicting a single new observation
"""Predict if the customer with the following informations will leave the bank:
Geography: France
Credit Score: 600
Gender: Male
Age: 40
Tenure: 3
Balance: 60000
Number of Products: 2
Has Credit Card: Yes
Is Active Member: Yes
Estimated Salary: 50000"""
new_prediction = classifier.predict(
    sc.transform(np.array([[0.0, 0, 600, 1, 40, 3, 60000, 2, 1, 1, 50000]]))
)
new_prediction = new_prediction > 0.5

# Making the Confusion Matrix
from sklearn.metrics import confusion_matrix

cm = confusion_matrix(y_test, y_pred)

# Part 4 - Evaluating, Improving and Tuning the ANN

# Evaluating the ANN
from keras.layers import Dense
from keras.models import Sequential
from keras.wrappers.scikit_learn import KerasClassifier
from sklearn.model_selection import cross_val_score


def build_classifier():
    classifier = Sequential()
    classifier.add(Dense(units=6, kernel_initializer="uniform", activation="relu", input_dim=11))
    classifier.add(Dense(units=6, kernel_initializer="uniform", activation="relu"))
    classifier.add(Dense(units=1, kernel_initializer="uniform", activation="sigmoid"))
    classifier.compile(optimizer="adam", loss="binary_crossentropy", metrics=["accuracy"])
    return classifier


classifier = KerasClassifier(build_fn=build_classifier, batch_size=10, epochs=100)
accuracies = cross_val_score(estimator=classifier, X=X_train, y=y_train, cv=10, n_jobs=-1)
mean = accuracies.mean()
variance = accuracies.std()

# Improving the ANN
# Dropout Regularization to reduce overfitting if needed

# Tuning the ANN
from keras.layers import Dense
from keras.models import Sequential
from keras.wrappers.scikit_learn import KerasClassifier
from sklearn.model_selection import GridSearchCV


def build_classifier(optimizer):
    classifier = Sequential()
    classifier.add(Dense(units=6, kernel_initializer="uniform", activation="relu", input_dim=11))
    classifier.add(Dense(units=6, kernel_initializer="uniform", activation="relu"))
    classifier.add(Dense(units=1, kernel_initializer="uniform", activation="sigmoid"))
    classifier.compile(optimizer=optimizer, loss="binary_crossentropy", metrics=["accuracy"])
    return classifier


classifier = KerasClassifier(build_fn=build_classifier)
parameters = {"batch_size": [25, 32], "epochs": [100, 500], "optimizer": ["adam", "rmsprop"]}
grid_search = GridSearchCV(estimator=classifier, param_grid=parameters, scoring="accuracy", cv=10)
grid_search = grid_search.fit(X_train, y_train)
best_parameters = grid_search.best_params_
best_accuracy = grid_search.best_score_
