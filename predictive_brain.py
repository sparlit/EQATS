"""
Self-Learning AI Prediction Brain - Neural Network MLP written in pure Python.
Autonomously predicts the direction of the next candle, continuously trains on live data,
calculates rolling accuracy, and adjusts its weights via backpropagation.
"""

import math
import random

class NeuralNetworkPredictor:
    """
    Lightweight, high-performance Multi-Layer Perceptron (MLP) Neural Network.
    Architecture:
      - Input Layer: 6 features (Normalized RSI, EMA Ratio, MACD Histogram, Return, Regime, Volatility Ratio)
      - Hidden Layer: 5 Neurons (Sigmoid activation)
      - Output Layer: 1 Neuron (Sigmoid activation, > 0.5 is Bullish, <= 0.5 is Bearish)
    """

    def __init__(self, learning_rate=0.1):
        self.learning_rate = learning_rate

        # Seed random for stable weight initialization
        random.seed(42)

        # 1. Initialize weights and biases with small random values
        # Input to Hidden Weights (6 inputs -> 5 hidden neurons)
        self.w_input_hidden = [[random.uniform(-0.5, 0.5) for _ in range(5)] for _ in range(6)]
        self.bias_hidden = [random.uniform(-0.1, 0.1) for _ in range(5)]

        # Hidden to Output Weights (5 hidden -> 1 output)
        self.w_hidden_output = [random.uniform(-0.5, 0.5) for _ in range(5)]
        self.bias_output = random.uniform(-0.1, 0.1)

        # 2. Performance Tracking
        self.last_inputs = None
        self.last_prediction = None
        self.correct_predictions = 0
        self.total_predictions = 0

    def _sigmoid(self, x):
        """Sigmoid activation function."""
        try:
            return 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, x)))) # clip limits to avoid overflow
        except OverflowError:
            return 0.0

    def _sigmoid_derivative(self, sigmoid_val):
        """Derivative of sigmoid given sigmoid(x)."""
        return sigmoid_val * (1.0 - sigmoid_val)

    def predict(self, inputs):
        """
        Runs forward propagation to predict next candle direction.
        inputs: list of 6 floats.
        Returns: float (probability of bullish direction [0.0, 1.0])
        """
        if len(inputs) != 6:
            return 0.5

        # 1. Forward to Hidden Layer
        self.hidden_activated = []
        for h in range(5):
            sum_h = self.bias_hidden[h]
            for i in range(6):
                sum_h += inputs[i] * self.w_input_hidden[i][h]
            self.hidden_activated.append(self._sigmoid(sum_h))

        # 2. Forward to Output Layer
        sum_o = self.bias_output
        for h in range(5):
            sum_o += self.hidden_activated[h] * self.w_hidden_output[h]

        output_activated = self._sigmoid(sum_o)

        self.last_inputs = inputs
        self.last_prediction = output_activated
        return output_activated

    def learn_and_adjust(self, actual_direction_bullish):
        """
        Compares previous prediction against the actual next candle outcome,
        updates rolling accuracy tracker, and runs backpropagation to adjust weights.
        actual_direction_bullish: int (1.0 for bullish close, 0.0 for bearish close)
        """
        if self.last_inputs is None or self.last_prediction is None:
            return

        # 1. Update rolling accuracy stats
        pred_bullish = 1.0 if self.last_prediction > 0.5 else 0.0
        is_correct = (pred_bullish == actual_direction_bullish)

        self.total_predictions += 1
        if is_correct:
            self.correct_predictions += 1

        # 2. Backpropagation
        # Target
        target = float(actual_direction_bullish)

        # Output error gradient
        output_delta = (target - self.last_prediction) * self._sigmoid_derivative(self.last_prediction)

        # Hidden layer error gradients
        hidden_deltas = []
        for h in range(5):
            err_h = output_delta * self.w_hidden_output[h]
            hidden_deltas.append(err_h * self._sigmoid_derivative(self.hidden_activated[h]))

        # 3. Update Hidden-to-Output weights and biases
        for h in range(5):
            self.w_hidden_output[h] += self.learning_rate * output_delta * self.hidden_activated[h]
        self.bias_output += self.learning_rate * output_delta

        # 4. Update Input-to-Hidden weights and biases
        for i in range(6):
            for h in range(5):
                self.w_input_hidden[i][h] += self.learning_rate * hidden_deltas[h] * self.last_inputs[i]

        for h in range(5):
            self.bias_hidden[h] += self.learning_rate * hidden_deltas[h]

    def get_accuracy(self):
        """Returns the rolling success accuracy percentage."""
        if self.total_predictions == 0:
            return 50.0  # Default baseline
        return round((self.correct_predictions / self.total_predictions) * 100.0, 2)

    def get_internal_state(self):
        """
        Exposes internal neural network parameters (weights, activations, biases)
        to visualize the training and convergence process happening inside the brain.
        """
        # Calculate averages of weights
        total_w_ih = sum(sum(w_row) for w_row in self.w_input_hidden)
        avg_w_ih = total_w_ih / 30.0 # 6 inputs * 5 hidden = 30 weights

        avg_w_ho = sum(self.w_hidden_output) / 5.0 # 5 hidden neurons

        hidden_str = ",".join(f"{h:.2f}" for h in getattr(self, 'hidden_activated', [0.0]*5))

        return {
            "avg_w_ih": round(avg_w_ih, 4),
            "avg_w_ho": round(avg_w_ho, 4),
            "bias_output": round(self.bias_output, 4),
            "hidden_activations": hidden_str,
            "training_cycles": self.total_predictions
        }


# Centralized predictive brain dictionary to keep track of predictors for each symbol
_predictor_registry = {}

def get_symbol_predictor(symbol):
    """Factory to fetch or create the dedicated predictor instance for a symbol."""
    sym_upper = symbol.upper()
    if sym_upper not in _predictor_registry:
        _predictor_registry[sym_upper] = NeuralNetworkPredictor()
    return _predictor_registry[sym_upper]
