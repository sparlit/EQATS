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


import time

import numpy as np
import tensorflow as tf


def reducedimension(input_, dimension=2, learning_rate=0.01, hidden_layer=256, epoch=20):

    input_size = input_.shape[1]
    X = tf.placeholder("float", [None, input_size])

    weights = {
        "encoder_h1": tf.Variable(tf.random_normal([input_size, hidden_layer])),
        "encoder_h2": tf.Variable(tf.random_normal([hidden_layer, dimension])),
        "decoder_h1": tf.Variable(tf.random_normal([dimension, hidden_layer])),
        "decoder_h2": tf.Variable(tf.random_normal([hidden_layer, input_size])),
    }

    biases = {
        "encoder_b1": tf.Variable(tf.random_normal([hidden_layer])),
        "encoder_b2": tf.Variable(tf.random_normal([dimension])),
        "decoder_b1": tf.Variable(tf.random_normal([hidden_layer])),
        "decoder_b2": tf.Variable(tf.random_normal([input_size])),
    }

    first_layer_encoder = tf.nn.sigmoid(tf.add(tf.matmul(X, weights["encoder_h1"]), biases["encoder_b1"]))
    second_layer_encoder = tf.nn.sigmoid(
        tf.add(tf.matmul(first_layer_encoder, weights["encoder_h2"]), biases["encoder_b2"])
    )
    first_layer_decoder = tf.nn.sigmoid(
        tf.add(tf.matmul(second_layer_encoder, weights["decoder_h1"]), biases["decoder_b1"])
    )
    second_layer_decoder = tf.nn.sigmoid(
        tf.add(tf.matmul(first_layer_decoder, weights["decoder_h2"]), biases["decoder_b2"])
    )
    cost = tf.reduce_mean(tf.pow(X - second_layer_decoder, 2))
    optimizer = tf.train.RMSPropOptimizer(learning_rate).minimize(cost)
    sess = tf.InteractiveSession()
    sess.run(tf.global_variables_initializer())

    for i in range(epoch):
        last_time = time.time()
        _, loss = sess.run([optimizer, cost], feed_dict={X: input_})
        if (i + 1) % 10 == 0:
            print("epoch:", i + 1, "loss:", loss, "time:", time.time() - last_time)

    vectors = sess.run(second_layer_encoder, feed_dict={X: input_})
    tf.reset_default_graph()
    return vectors
