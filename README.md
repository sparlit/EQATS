# Elite Autonomous Quantum Trading System

Welcome to the **Elite Autonomous Quantum Trading System**—a professional, hedge-fund-grade quantitative trading platform configured to interface natively with **MetaTrader 5 (MT5)** on Windows, as well as run in high-fidelity simulated paper-trading modes on any Unix/Linux sandbox.

This platform represents the absolute pinnacle of algorithmic asset execution. It consolidates advanced mathematical solvers, machine learning frameworks, NLP news classifiers, and high-capacity vector indices to achieve unmatched predictive success and risk-adjusted yield.

---

## 🚀 Key Architectural Pillars

### 1. Multi-Style & Multi-Strategy Voting Engine (`brain.py` & `indicators.py`)
- **4 Operational Styles:** Scalping (fast tick intervals), Day Trading, Swing Trading, and Position Trading.
- **9 High-Performance Strategies:**
  1. **Trend-Following (EMA & RSI):** Crossover entries aligned with long-term trends.
  2. **Mean Reversion (Bollinger Bands & RSI):** Oversold/Overbought counter-trend reversals.
  3. **MACD Momentum:** Real-time histogram directional swings.
  4. **Donchian Squeeze Breakout:** Narrow Bollinger squeeze channels with Donchian breakouts.
  5. **Carry Rollover Yield:** Leverages positive interest yield swaps while blocking high negative carry cost structures.
  6. **Cost-Averaging Grid Trading:** Opens dynamic multiple grid layers spaced by ATR increments.
  7. **Statistical Arbitrage:** Spread ratio trading using historical standard deviation z-scores.
  8. **Opening Range Breakout (ORB):** Breakout alerts on the high/low bounds of the opening session range.
  9. **Volume-Spread Analysis (VSA):** Identifies institutional accumulation and distribution on high volume.
- **Regime-Adaptive Voting consensus:** Statistical Gaussian classifiers categorize environments as Trending vs. Ranging, automatically shifting individual strategy vote weights dynamically.

### 2. Deep Ensemble Machine Learning (`predictive_brain.py`)
- **6-Feature MLP Neural Network:** Input parameters include Normalized RSI, EMA Ratio, MACD, Returns, Regime Index, and Volatility Coefficients.
- **Continuous Backpropagation Learning:** Trains on actual candle close outcomes to predict the next trend bias and veto technically false setups.

### 3. Stunning Bloomberg Professional Terminal GUI (`gui.py`)
- Dark pitch-black theme utilizing orange, neon green, and cyan Consolas monospace typography.
- Supporting authentic Bloomberg CLI commands (`MAIN <GO>`, `GP <GO>`, `PORT <GO>`, `MCTS <GO>`, etc.).
- **Interactive Sheets:**
  - `PORT <GO>`: Portfolio Mean-Variance Sharpe optimization using Polars and JAX.
  - `MCTS <GO>`: Volatility random walk generator computing Value at Risk (VaR) and Expected Shortfall (ES).
  - `VDS <GO>`: Semantic FAISS nearest-neighbor searches.

### 4. Native MT5 HUD Expert Advisor Integration (`ScalperBrainEA.mq5`)
- Seamless real-time visual HUD dashboard drawn directly on live MetaTrader 5 charts by sharing metrics via MT5's common `FILE_COMMON` directory.

### 5. Multi-Library Institutional Suite (`institutional_integrations/`)
Integrates over 110+ premium quantitative, mathematical, and data science libraries with dynamic, exception-defensive imports:
- **Data Science:** NumPy, Pandas, Polars, Vaex, Dask, JAX, Statsmodels, Pingouin.
- **Machine Learning:** PyTorch, TensorFlow, Keras, Scikit-learn, XGBoost, LightGBM, CatBoost, Prophet, Darts, tsfresh, AutoTS.
- **NLP:** Hugging Face Transformers, spaCy, NLTK, TextBlob, LangChain, LlamaIndex, EdgarTools, Gensim.
- **Databases:** DuckDB, SQLAlchemy, PeeWee, TinyDB, Neo4j, NetworkX, FAISS, ChromaDB, Pinecone.
- **Web & Messaging:** FastAPI, Flask, Robyn, Kafka, Airflow.
- **Advanced Math:** QuantLib Option Pricing, PyMC3/PyStan Bayesian chains, MSAR Volatility models.
- **Hardware & Matching Engines:** Raspberry Pi GPIO mocks, Redis Queues, Rust execution bridges.

---

## 💻 Running the Platform

To verify the installation and run the dynamic unit test suite:
```bash
pytest
```
To launch the Bloomberg Terminal GUI:
```bash
python3 main.py
```
*(If a headless server is detected, the system will fall back gracefully to the interactive console client).*
