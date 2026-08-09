import indicators
import config
import database
import predictive_brain

class ScalperBrain:
    """
    The main decision engine. Analyzes historical price bar data,
    performs indicators calculations, evaluates trade setups, computes dynamic lot sizes,
    and returns actions with self-explanatory trading statements.
    """

    def __init__(self):
        pass

    def evaluate(self, symbol, history_bars, current_equity):
        """
        Analyzes historical bars and gives a decision: 'BUY', 'SELL', or 'HOLD'.
        history_bars: list of dicts/objects with keys: 'open', 'high', 'low', 'close'
        current_equity: float, current account balance/equity to calculate lot size.
        """
        # Ensure we have enough data to calculate all indicators
        min_bars_needed = max(config.EMA_LONG_PERIOD + 10, config.RSI_PERIOD + 10, config.ATR_PERIOD + 10, config.MACD_SLOW + 15)

        if len(history_bars) < min_bars_needed:
            msg = f"Insufficient history data for {symbol}. Needs {min_bars_needed} bars, got {len(history_bars)}."
            database.log_assessment(symbol, "UNKNOWN", None, None, "HOLD", msg)
            return {
                'decision': 'HOLD',
                'lot_size': 0.0,
                'sl': 0.0,
                'tp': 0.0,
                'explanation': msg,
                'indicators': {}
            }

        closes = [bar['close'] for bar in history_bars]
        highs = [bar['high'] for bar in history_bars]
        lows = [bar['low'] for bar in history_bars]

        current_price = closes[-1]

        # Calculate all active indicators
        ema_long = indicators.calculate_ema(closes, config.EMA_LONG_PERIOD)
        ema_short = indicators.calculate_ema(closes, config.EMA_SHORT_PERIOD)
        ema_medium = indicators.calculate_ema(closes, config.EMA_MEDIUM_PERIOD)
        rsi_val = indicators.calculate_rsi(closes, config.RSI_PERIOD)
        atr_val = indicators.calculate_atr(highs, lows, closes, config.ATR_PERIOD)
        bb = indicators.calculate_bollinger_bands(closes, config.BB_PERIOD, config.BB_STD_DEV)
        macd = indicators.calculate_macd(closes, config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL)

        if ema_long is None or rsi_val is None or atr_val is None or ema_short is None or ema_medium is None or bb is None or macd is None:
            msg = f"Indicator calculation returned None for {symbol} due to insufficient history window."
            database.log_assessment(symbol, "UNKNOWN", None, None, "HOLD", msg)
            return {
                'decision': 'HOLD',
                'lot_size': 0.0,
                'sl': 0.0,
                'tp': 0.0,
                'explanation': msg,
                'indicators': {}
            }

        trend_direction = "UP" if current_price > ema_long else "DOWN"

        # --- AI Predictor Integration and Learning ---
        predictor = predictive_brain.get_symbol_predictor(symbol)

        # Classify market regime to pass as additional neural inputs
        reg_info_nn = indicators.classify_market_regime(highs, lows, closes)
        reg_state_val = 1.0 if reg_info_nn['regime'] == "TRENDING" else 0.0

        # Calculate volatility ratio
        baseline_atr_nn = sum(indicators.calculate_atr(highs[:i], lows[:i], closes[:i], config.ATR_PERIOD) or atr_val for i in range(len(closes) - 20, len(closes))) / 20.0
        vol_ratio = atr_val / baseline_atr_nn if baseline_atr_nn > 0 else 1.0

        # Prepare inputs (Expanded to 6 features for institutional intelligence)
        rsi_norm = rsi_val / 100.0
        ema_ratio = ema_short / ema_medium if ema_medium > 0 else 1.0
        macd_ratio = macd['histogram'] / current_price if current_price > 0 else 0.0
        returns_prev = (closes[-1] - closes[-2]) / closes[-2] if len(closes) >= 2 else 0.0

        inputs = [rsi_norm, ema_ratio, macd_ratio, returns_prev, reg_state_val, vol_ratio]

        # Train on actual open-to-close outcome of previous candle
        actual_bullish_close = 1.0 if closes[-1] > closes[-2] else 0.0
        predictor.learn_and_adjust(actual_bullish_close)

        # Predict next candle bullish probability
        ai_bullish_prob = predictor.predict(inputs)
        ai_pred_direction = "BULLISH" if ai_bullish_prob > 0.5 else "BEARISH"
        ai_accuracy = predictor.get_accuracy()

        # 1. EVALUATE STRATEGY 1: TREND_FOLLOWING (EMA + RSI)
        sig_tf = "HOLD"
        reasons_tf = []
        if trend_direction == "UP":
            if rsi_val <= config.RSI_BUY_THRESHOLD and ema_short > ema_medium:
                sig_tf = "BUY"
            else:
                if rsi_val > config.RSI_BUY_THRESHOLD:
                    reasons_tf.append(f"RSI {rsi_val:.1f} > {config.RSI_BUY_THRESHOLD}")
                if ema_short <= ema_medium:
                    reasons_tf.append("EMA-9 below EMA-21")
        else: # DOWN trend
            if rsi_val >= config.RSI_SELL_THRESHOLD and ema_short < ema_medium:
                sig_tf = "SELL"
            else:
                if rsi_val < config.RSI_SELL_THRESHOLD:
                    reasons_tf.append(f"RSI {rsi_val:.1f} < {config.RSI_SELL_THRESHOLD}")
                if ema_short >= ema_medium:
                    reasons_tf.append("EMA-9 above EMA-21")

        # 2. EVALUATE STRATEGY 2: MEAN_REVERSION (Bollinger Bands)
        sig_mr = "HOLD"
        reasons_mr = []
        if current_price <= bb['lower'] and rsi_val <= 30.0:
            sig_mr = "BUY"
        elif current_price >= bb['upper'] and rsi_val >= 70.0:
            sig_mr = "SELL"
        else:
            if current_price > bb['lower'] and current_price < bb['upper']:
                reasons_mr.append("Price inside Bands")
            if rsi_val > 30.0 and rsi_val < 70.0:
                reasons_mr.append(f"RSI {rsi_val:.1f} neutral")

        # 3. EVALUATE STRATEGY 3: MACD_MOMENTUM
        sig_mac = "HOLD"
        reasons_mac = []
        if macd['histogram'] > 0 and macd['macd'] > macd['signal']:
            sig_mac = "BUY"
        elif macd['histogram'] < 0 and macd['macd'] < macd['signal']:
            sig_mac = "SELL"
        else:
            reasons_mac.append("MACD neutral")

        # 4. EVALUATE STRATEGY 4: BREAKOUT (Donchian Channels + Bollinger Squeeze)
        sig_bo = "HOLD"
        reasons_bo = []
        donchian = indicators.calculate_donchian_channels(highs, lows, config.BREAKOUT_PERIOD)
        squeeze = indicators.calculate_bollinger_squeeze(closes, config.BB_PERIOD, config.BB_STD_DEV)

        if donchian and squeeze is not None:
            # Squeeze is active if bandwidth is tight
            is_squeezed = squeeze < 0.04
            if is_squeezed:
                # Squeeze breakout setup
                if current_price >= donchian['upper']:
                    sig_bo = "BUY"
                elif current_price <= donchian['lower']:
                    sig_bo = "SELL"
                else:
                    reasons_bo.append(f"Inside Squeeze Channel [{donchian['lower']:.5f} - {donchian['upper']:.5f}]")
            else:
                reasons_bo.append(f"Bandwidth too high: {squeeze:.3f}")
        else:
            reasons_bo.append("Breakout indicators unavailable")

        # 5. EVALUATE STRATEGY 5: CARRY_TRADE (Rollover / Interest Yield Arbitrage)
        sig_cy = "HOLD"
        reasons_cy = []
        swap_val = config.SWAP_LONG_POINTS.get(symbol.upper(), 0.0)

        if abs(swap_val) >= config.MIN_CARRY_YIELD_POINTS:
            if swap_val > 0 and trend_direction == "UP" and rsi_val <= 60:
                sig_cy = "BUY"
            elif swap_val < 0 and trend_direction == "DOWN" and rsi_val >= 40:
                sig_cy = "SELL"
            else:
                reasons_cy.append(f"Trend/RSI divergence with swap {swap_val:+.1f}")
        else:
            reasons_cy.append(f"Carry yield {swap_val:+.1f} below minimum {config.MIN_CARRY_YIELD_POINTS}")

        # 6. EVALUATE STRATEGY 6: GRID_TRADE (Cost-Averaging Matrix)
        sig_gd = "HOLD"
        reasons_gd = []
        # Query active open positions for cost average spacing checks
        try:
            recent_assessments = database.get_recent_performance(count=1)
            # GRID rules will be evaluated by looking at active positions inside main execution loop
            # Here we provide grid bias triggers based on Bollinger outer bounds
            if rsi_val <= 40:
                sig_gd = "BUY"
            elif rsi_val >= 60:
                sig_gd = "SELL"
            else:
                reasons_gd.append("RSI too neutral for grid bias placement")
        except Exception:
            sig_gd = "HOLD"

        # Choose the dynamic trading setup based on user's active strategy configuration
        strategy_mode = config.ACTIVE_STRATEGY
        decision = "HOLD"
        explanation = ""

        # Classify market regime to dynamically weight voting strategies!
        reg_info = indicators.classify_market_regime(highs, lows, closes)
        reg_state = reg_info['regime']
        reg_vol = reg_info['volatility']

        if strategy_mode == "TREND_FOLLOWING":
            decision = sig_tf
            explanation = f"Trend Setup: {decision if decision != 'HOLD' else 'Waiting for: ' + ' & '.join(reasons_tf)}"
        elif strategy_mode == "MEAN_REVERSION":
            decision = sig_mr
            explanation = f"Mean Reversion Setup: {decision if decision != 'HOLD' else 'Waiting for: ' + ' & '.join(reasons_mr)}"
        elif strategy_mode == "MACD_MOMENTUM":
            decision = sig_mac
            explanation = f"MACD Setup: {decision if decision != 'HOLD' else 'Waiting for: ' + ' & '.join(reasons_mac)}"
        elif strategy_mode == "BREAKOUT":
            decision = sig_bo
            explanation = f"Breakout Setup: {decision if decision != 'HOLD' else 'Waiting for: ' + ' & '.join(reasons_bo)}"
        elif strategy_mode == "CARRY_TRADE":
            decision = sig_cy
            explanation = f"Carry Trade: {decision if decision != 'HOLD' else 'Waiting for: ' + ' & '.join(reasons_cy)}"
        elif strategy_mode == "GRID_TRADE":
            decision = sig_gd
            explanation = f"Grid Placement Bias: {decision if decision != 'HOLD' else 'Waiting for: ' + ' & '.join(reasons_gd)}"
        else: # VOTING_ENSEMBLE
            # Convert signals to numeric values (+1: BUY, -1: SELL, 0: HOLD)
            sig_to_val = lambda s: 1.0 if s == "BUY" else (-1.0 if s == "SELL" else 0.0)

            tf_val = sig_to_val(sig_tf)
            mr_val = sig_to_val(sig_mr)
            mac_val = sig_to_val(sig_mac)
            bo_val = sig_to_val(sig_bo)
            cy_val = sig_to_val(sig_cy)

            # Assign adaptive weights based on current market regime!
            tf_w, mr_w, mac_w, bo_w, cy_w = 1.0, 1.0, 1.0, 1.0, 0.5

            if reg_state == "TRENDING":
                tf_w = 2.0   # Trend is strong: boost trend following
                bo_w = 2.0   # Boost breakout follow-through
                mr_w = 0.0   # Disable mean-reversion counter-trend trades to avoid getting run over
            else: # RANGING
                mr_w = 2.5   # Rangebound: heavily boost mean reversion osc
                tf_w = 0.1   # Suppress trend following whipsaws
                bo_w = 0.1   # Suppress false breakouts

            total_weight = tf_w + mr_w + mac_w + bo_w + cy_w
            weighted_score = (tf_val * tf_w) + (mr_val * mr_w) + (mac_val * mac_w) + (bo_val * bo_w) + (cy_val * cy_w)
            normalized_score = weighted_score / total_weight if total_weight > 0 else 0.0

            ensemble_bias = "HOLD"
            if normalized_score >= 0.35:
                ensemble_bias = "BUY"
            elif normalized_score <= -0.35:
                ensemble_bias = "SELL"

            if ensemble_bias == "BUY":
                # Blindspot Protection: Filter Buy if AI next-candle is bearish
                if ai_pred_direction == "BULLISH":
                    decision = "BUY"
                    explanation = f"Regime Consensus BUY ({reg_state}/{reg_vol}) with AI Bullish convergence! Score: {normalized_score:.2f}"
                else:
                    decision = "HOLD"
                    explanation = f"Consensus BUY vetoed: AI predicts Bearish candle ({ai_accuracy}% acc). Score: {normalized_score:.2f}"
            elif ensemble_bias == "SELL":
                # Blindspot Protection: Filter Sell if AI next-candle is bullish
                if ai_pred_direction == "BEARISH":
                    decision = "SELL"
                    explanation = f"Regime Consensus SELL ({reg_state}/{reg_vol}) with AI Bearish convergence! Score: {normalized_score:.2f}"
                else:
                    decision = "HOLD"
                    explanation = f"Consensus SELL vetoed: AI predicts Bullish candle ({ai_accuracy}% acc). Score: {normalized_score:.2f}"
            else:
                decision = "HOLD"
                explanation = f"Regime {reg_state} ({reg_vol}) Voting: Neutral hold (Score: {normalized_score:+.2f}). AI Bias: {ai_pred_direction}"

        # Apply Institutional NLP Sentiment-News Veto Filter
        try:
            prevailing_sentiment = database.get_prevailing_news_sentiment()
            if prevailing_sentiment == "BULLISH" and decision == "SELL":
                decision = "HOLD"
                explanation = f"HOLD (Macro Vetoed: High-priority News Sentiment is BULLISH!) | {explanation}"
            elif prevailing_sentiment == "BEARISH" and decision == "BUY":
                decision = "HOLD"
                explanation = f"HOLD (Macro Vetoed: High-priority News Sentiment is BEARISH!) | {explanation}"
        except Exception as e:
            print(f"Warning: News sentiment filter error: {e}")

        # Dynamic Stop Loss and Take Profit with Volatility-Adaptive Profit Multiples
        sl = 0.0
        tp = 0.0
        lot_size = 0.0

        # ADAPT ATR MULTIPLIER AND HOLDING RATIO BY ACTIVE TRADING STYLE!
        style_mode = config.TRADING_STYLE
        style_multiplier = 1.5  # SCALPING base
        style_target_rr = config.RISK_REWARD_RATIO

        if style_mode == "DAY_TRADING":
            style_multiplier = 2.5
            style_target_rr = 2.0
        elif style_mode == "SWING_TRADING":
            style_multiplier = 4.0
            style_target_rr = 3.0
        elif style_mode == "POSITION_TRADING":
            style_multiplier = 6.0
            style_target_rr = 4.5

        sl_distance = max(atr_val * style_multiplier, current_price * 0.0010)

        # Calculate a baseline ATR to adapt Take Profit ratio
        baseline_atr = sum(indicators.calculate_atr(highs[:i], lows[:i], closes[:i], config.ATR_PERIOD) or atr_val for i in range(len(closes) - 20, len(closes))) / 20.0
        if baseline_atr <= 0:
            baseline_atr = atr_val

        # Volatility adaptation multiplier
        volatility_ratio = atr_val / baseline_atr if baseline_atr > 0 else 1.0
        adaptive_rr = style_target_rr
        if volatility_ratio > 1.2:
            adaptive_rr = style_target_rr * 1.25  # Heavy trend: scale up targets
        elif volatility_ratio < 0.8:
            adaptive_rr = style_target_rr * 0.75  # Consolidating/Quiet: pull targets in closer for high-probability win exits

        if decision == "BUY":
            sl = current_price - sl_distance
            tp = current_price + (sl_distance * adaptive_rr)
            lot_size = self._calculate_lot_size(symbol, current_equity, sl_distance)
        elif decision == "SELL":
            sl = current_price + sl_distance
            tp = current_price - (sl_distance * adaptive_rr)
            lot_size = self._calculate_lot_size(symbol, current_equity, sl_distance)

        database.log_assessment(
            symbol=symbol,
            trend_direction=trend_direction,
            rsi_val=rsi_val,
            atr_val=atr_val,
            decision=decision,
            explanation=explanation
        )

        return {
            'decision': decision,
            'lot_size': round(lot_size, 2),
            'sl': round(sl, 5),
            'tp': round(tp, 5),
            'explanation': explanation,
            'indicators': {
                'ema_long': round(ema_long, 5),
                'rsi': round(rsi_val, 2),
                'atr': round(atr_val, 5)
            }
        }

    def _calculate_lot_size(self, symbol, equity, sl_distance):
        """
        Calculates the appropriate lot size to risk on current equity using
        mathematical Kelly Criterion optimization and Performance-Adaptive Risk Sizing.
        """
        base_risk_pct = config.RISK_PER_TRADE_PERCENT
        using_kelly = False
        kelly_val = 0.0

        # Query past trade stats to calculate Kelly Sizing mathematically if history is rich
        try:
            conn_db = database.get_connection()
            cursor = conn_db.cursor()
            cursor.execute("SELECT profit FROM trades WHERE status = 'CLOSED'")
            rows = cursor.fetchall()
            conn_db.close()

            if len(rows) >= 10:
                profits = [r['profit'] for r in rows if r['profit'] is not None]
                wins = [p for p in profits if p > 0.0]
                losses = [abs(p) for p in profits if p <= 0.0]

                if len(profits) >= 10 and len(wins) > 0 and len(losses) > 0:
                    win_rate = len(wins) / len(profits)
                    avg_win = sum(wins) / len(wins)
                    avg_loss = sum(losses) / len(losses)
                    profit_factor = avg_win / avg_loss if avg_loss > 0 else 1.0

                    # Standard Kelly formula: K% = W - ((1 - W) / R)
                    kelly_fraction = win_rate - ((1.0 - win_rate) / profit_factor) if profit_factor > 0 else 0.0

                    if kelly_fraction > 0:
                        # Use Quarter-Kelly fraction to ensure safe risk boundaries
                        base_risk_pct = (kelly_fraction * 0.25) * 100.0
                        # Cap risk at hard ceilings [0.1%, 1.5%]
                        base_risk_pct = max(0.1, min(base_risk_pct, 1.5))
                        using_kelly = True
                        kelly_val = kelly_fraction
                    else:
                        base_risk_pct = 0.25 # Underperforming: reduce risk fraction to Quarter-Percent

            # Fallback to Streak-Adaptive Downscaling if not rich history or experiencing dynamic streaks
            if not using_kelly:
                recent_trades = database.get_recent_performance(count=4)
                if len(recent_trades) >= 3:
                    losses_count = sum(1 for t in recent_trades if t['profit'] is not None and t['profit'] < 0)
                    if losses_count == 3:
                        base_risk_pct = base_risk_pct * 0.5
                        print(f"🛡️ PERFORMANCE ADAPTATION: Drawdown streak detected (3 losses). Downscaling trade risk to {base_risk_pct:.2f}% to protect equity.")
                    elif losses_count >= 4:
                        base_risk_pct = base_risk_pct * 0.25
                        print(f"🛡️ PERFORMANCE ADAPTATION: Severe Drawdown streak detected (4 losses). Downscaling trade risk to {base_risk_pct:.2f}% to preserve capital.")
        except Exception as e:
            print(f"Warning: Kelly/Sizing adaptation calculation error: {e}")

        if using_kelly:
            print(f"🧮 KELLY CRITERION SIZING: Optimizing risk fraction to {base_risk_pct:.2f}% based on Kelly mathematical edge (K={kelly_val:.4f}).")

        risk_amount = equity * (base_risk_pct / 100.0)

        # Contract size mapping
        contract_size = 100000.0  # Default to Forex standard lot size

        symbol_upper = symbol.upper()
        if "USD" in symbol_upper:
            # Let's adjust contract sizes
            if "XAU" in symbol_upper or "GOLD" in symbol_upper:
                contract_size = 100.0
            elif "XAG" in symbol_upper or "SILVER" in symbol_upper:
                contract_size = 5000.0
            elif any(c in symbol_upper for c in ["BTC", "ETH", "LTC", "SOL", "XRP"]):
                contract_size = 1.0
            elif "JPY" in symbol_upper:
                # USDJPY contract is 100,000, but pip is 0.01 (divide by 100 to scale with USD)
                contract_size = 100000.0 / 100.0

        # Risk per 1 standard lot = contract_size * sl_distance
        risk_per_lot = contract_size * sl_distance

        if risk_per_lot <= 0:
            return 0.01

        lot_size = risk_amount / risk_per_lot

        # Limit lot sizes to reasonable bounds [0.01, 10.0]
        lot_size = max(0.01, min(lot_size, 10.0))
        return lot_size
