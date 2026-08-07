import indicators
import config
import database

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

        # Choose the dynamic trading setup based on user's active strategy configuration
        strategy_mode = config.ACTIVE_STRATEGY
        decision = "HOLD"
        explanation = ""

        if strategy_mode == "TREND_FOLLOWING":
            decision = sig_tf
            explanation = f"Trend Setup: {decision if decision != 'HOLD' else 'Waiting for: ' + ' & '.join(reasons_tf)}"
        elif strategy_mode == "MEAN_REVERSION":
            decision = sig_mr
            explanation = f"Mean Reversion Setup: {decision if decision != 'HOLD' else 'Waiting for: ' + ' & '.join(reasons_mr)}"
        elif strategy_mode == "MACD_MOMENTUM":
            decision = sig_mac
            explanation = f"MACD Setup: {decision if decision != 'HOLD' else 'Waiting for: ' + ' & '.join(reasons_mac)}"
        else: # VOTING_ENSEMBLE
            votes = [sig_tf, sig_mr, sig_mac]
            buy_votes = votes.count("BUY")
            sell_votes = votes.count("SELL")

            if buy_votes >= 2 and sell_votes == 0:
                decision = "BUY"
                explanation = f"Ensemble BUY signal triggered with {buy_votes} strategy consensus!"
            elif sell_votes >= 2 and buy_votes == 0:
                decision = "SELL"
                explanation = f"Ensemble SELL signal triggered with {sell_votes} strategy consensus!"
            else:
                decision = "HOLD"
                # Formulate detailed hold summaries of each module
                explanation = f"Voting: Hold. (Trend: {sig_tf} | Reversion: {sig_mr} | MACD: {sig_mac})"

        # Dynamic Stop Loss and Take Profit with Volatility-Adaptive Profit Multiples
        sl = 0.0
        tp = 0.0
        lot_size = 0.0
        sl_distance = max(atr_val * config.ATR_MULTIPLIER_SL, current_price * 0.0005)

        # Calculate a baseline ATR to adapt Take Profit ratio
        baseline_atr = sum(indicators.calculate_atr(highs[:i], lows[:i], closes[:i], config.ATR_PERIOD) or atr_val for i in range(len(closes) - 20, len(closes))) / 20.0
        if baseline_atr <= 0:
            baseline_atr = atr_val

        # Volatility adaptation multiplier
        volatility_ratio = atr_val / baseline_atr if baseline_atr > 0 else 1.0
        adaptive_rr = config.RISK_REWARD_RATIO
        if volatility_ratio > 1.2:
            adaptive_rr = 2.5  # Heavy trend: scale up targets
        elif volatility_ratio < 0.8:
            adaptive_rr = 1.5  # Consolidating/Quiet: pull targets in closer for high-probability win exits

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
        Calculates the appropriate lot size to risk exactly config.RISK_PER_TRADE_PERCENT of current equity.
        Formula:
        Risk Amount = Equity * (Risk % / 100)

        This method is enhanced with Adaptive Risk Sizing:
        - If the bot has recently taken a streak of consecutive losses,
          it autonomously downscales the risk % to protect account equity!
        """
        # A. Query recent trade performance to adapt risk
        base_risk_pct = config.RISK_PER_TRADE_PERCENT

        try:
            recent_trades = database.get_recent_performance(count=4)
            if len(recent_trades) >= 3:
                losses = sum(1 for t in recent_trades if t['profit'] is not None and t['profit'] < 0)
                if losses == 3:
                    base_risk_pct = base_risk_pct * 0.5 # Scale down risk by 50%
                    print(f"🛡️ PERFORMANCE ADAPTATION: Drawdown streak detected (3 losses). Downscaling trade risk to {base_risk_pct:.2f}% to protect equity.")
                elif losses >= 4:
                    base_risk_pct = base_risk_pct * 0.25 # Scale down risk by 75%
                    print(f"🛡️ PERFORMANCE ADAPTATION: Severe Drawdown streak detected (4 losses). Downscaling trade risk to {base_risk_pct:.2f}% to preserve capital.")
        except Exception as e:
            print(f"Warning: Risk adaptation query error: {e}")

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
