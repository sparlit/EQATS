# TODO LIST: INSTITUTIONAL-GRADE ALGORITHMIC TRADING SYSTEM

This document tracks the progress of advanced institutional enhancements designed to turn our multi-strategy platform into an unmatchable, industry-leading trading framework.

---

## 📋 Task Checklist

- [x] **Task 1: Market Regime Classifier (Trending vs. Ranging)**
  - Implement a statistical regime filter in `indicators.py` evaluating Average Directional Index (ADX) proxy or Bollinger Band Width standard deviations.
  - Integrate regime metrics into `brain.py` to auto-tune active strategies (e.g. prioritize `TREND_FOLLOWING` during trends, and `MEAN_REVERSION` during ranging regimes).

- [x] **Task 2: Kelly Criterion Dynamic Position Sizing**
  - Implement a Kelly fraction lot calculation engine in `brain.py` that queries closed trade statistics (Win Rate $W$ and Win/Loss Ratio $R$) to optimize compounding yields.
  - Implement protective fractional-Kelly caps (e.g., Quarter-Kelly or Half-Kelly) to secure account equity.

- [x] **Task 3: NLP Macro News Sentiment Filters**
  - Expand `brain.py` and `main.py` to parse live macro news sentiment feeds.
  - Automatically veto consensus signals if they run contrary to prevailing high-priority macro-sentiment (e.g., blocking Longs if news sentiment is extremely BEARISH).

- [x] **Task 4: AI Neural Network Predictive Feature Expansion**
  - Enrich the pure-Python Multi-Layer Perceptron (MLP) in `predictive_brain.py` with multi-timeframe and regime inputs (Regime Index, ATR volatility ratios, MACD slopes).
  - Train on expanded input features to improve next-candle accuracy and suppress trend divergence blind spots.

---

## 📈 Completion Log
- **Task 1 Complete:** Statistical Market Regime Classifier fully active. Dynamically tunes strategy voting weights (Trends boost Trend following, Ranges favor Bollinger oscillators).
- **Task 2 Complete:** Mathematical Kelly Criterion Dynamic Position Sizing active. Utilizes Quarter-Kelly compounding equations derived from live database metrics, protected by dynamic risk ceilings.
- **Task 3 Complete:** Natural Language Processing (NLP) Macro News Sentiment Filter active. Logs real-time terminal headlines to SQLite and autonomously vetoes counter-news trade proposals.
- **Task 4 Complete:** Predictive AI Brain Expanded. Multi-Layer Perceptron neural network inputs upgraded to 6 features (including live statistical market regimes and ATR-volatility ratio coefficients) to elevate prediction accuracy.
