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

        Returns:
            dict with structure:
            {
                'decision': 'BUY' | 'SELL' | 'HOLD',
                'lot_size': float,
                'sl': float,
                'tp': float,
                'explanation': str,
                'indicators': { 'ema_long': float, 'rsi': float, 'atr': float }
            }
        """
        # Ensure we have enough data to calculate EMA-200 and other indicators
        min_bars_needed = max(config.EMA_LONG_PERIOD + 10, config.RSI_PERIOD + 10, config.ATR_PERIOD + 10)

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

        # Calculate indicators
        ema_long = indicators.calculate_ema(closes, config.EMA_LONG_PERIOD)
        ema_short = indicators.calculate_ema(closes, config.EMA_SHORT_PERIOD)
        ema_medium = indicators.calculate_ema(closes, config.EMA_MEDIUM_PERIOD)
        rsi_val = indicators.calculate_rsi(closes, config.RSI_PERIOD)
        atr_val = indicators.calculate_atr(highs, lows, closes, config.ATR_PERIOD)

        if ema_long is None or rsi_val is None or atr_val is None or ema_short is None or ema_medium is None:
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

        # Trend filter definition (using 200 EMA)
        trend_direction = "UP" if current_price > ema_long else "DOWN"

        # Trading assessment setup
        decision = 'HOLD'
        sl = 0.0
        tp = 0.0
        lot_size = 0.0
        explanation = ""

        # ATR multiplier for Stop Loss
        sl_distance = max(atr_val * config.ATR_MULTIPLIER_SL, current_price * 0.0005) # Floor at 0.05% of price to avoid zero-distance errors

        if trend_direction == "UP":
            # Long Setup logic: Fast EMA-9 crossing/staying above EMA-21, plus price pullbacks where RSI is oversold
            # RSI oversold signals an opportunistic entry in an overall uptrend
            if rsi_val <= config.RSI_BUY_THRESHOLD and ema_short > ema_medium:
                decision = 'BUY'
                sl = current_price - sl_distance
                tp = current_price + (sl_distance * config.RISK_REWARD_RATIO)

                lot_size = self._calculate_lot_size(symbol, current_equity, sl_distance)
                explanation = (
                    f"Trend is UP (Price {current_price:.5f} > 200 EMA {ema_long:.5f}). "
                    f"Momentum EMA-9 {ema_short:.5f} is above EMA-21 {ema_medium:.5f}. "
                    f"RSI is oversold at {rsi_val:.2f} (<= {config.RSI_BUY_THRESHOLD}). "
                    f"Triggering BUY order."
                )
            else:
                explanation = (
                    f"Trend is UP (Price {current_price:.5f} > 200 EMA {ema_long:.5f}). "
                    f"RSI is {rsi_val:.2f} (Buy requires <= {config.RSI_BUY_THRESHOLD}). "
                    f"EMA-9 {ema_short:.5f} vs EMA-21 {ema_medium:.5f}. "
                    f"No entry condition met. Holding."
                )

        elif trend_direction == "DOWN":
            # Short Setup logic: Fast EMA-9 crossing/staying below EMA-21, plus price pullbacks where RSI is overbought
            # RSI overbought signals an opportunistic short entry in an overall downtrend
            if rsi_val >= config.RSI_SELL_THRESHOLD and ema_short < ema_medium:
                decision = 'SELL'
                sl = current_price + sl_distance
                tp = current_price - (sl_distance * config.RISK_REWARD_RATIO)

                lot_size = self._calculate_lot_size(symbol, current_equity, sl_distance)
                explanation = (
                    f"Trend is DOWN (Price {current_price:.5f} < 200 EMA {ema_long:.5f}). "
                    f"Momentum EMA-9 {ema_short:.5f} is below EMA-21 {ema_medium:.5f}. "
                    f"RSI is overbought at {rsi_val:.2f} (>= {config.RSI_SELL_THRESHOLD}). "
                    f"Triggering SELL order."
                )
            else:
                explanation = (
                    f"Trend is DOWN (Price {current_price:.5f} < 200 EMA {ema_long:.5f}). "
                    f"RSI is {rsi_val:.2f} (Sell requires >= {config.RSI_SELL_THRESHOLD}). "
                    f"EMA-9 {ema_short:.5f} vs EMA-21 {ema_medium:.5f}. "
                    f"No entry condition met. Holding."
                )

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
        Pip Value calculations vary by symbol type. We can use generalized point/pip values:
        For standard currency pairs:
        1 standard lot = 100,000 units.
        For a risk distance of sl_distance:
        For EURUSD (tick size ~ 0.00001, pip size ~ 0.0001):
        Loss per standard lot = 100,000 * sl_distance (quote currency).
        Let's use robust multipliers for each class of symbols:
        - Forex: standard lot size contract is 100,000 units.
        - Gold (XAUUSD): standard contract size is 100 oz.
        - Crypto (BTCUSD, ETHUSD): standard contract size is 1.
        """
        risk_amount = equity * (config.RISK_PER_TRADE_PERCENT / 100.0)

        # Contract size mapping
        contract_size = 100000.0  # Default to Forex standard lot size

        symbol_upper = symbol.upper()
        if "USD" in symbol_upper:
            # Let's adjust contract sizes
            if "XAU" in symbol_upper or "GOLD" in symbol_upper:
                contract_size = 100.0
            elif "BTC" in symbol_upper or "ETH" in symbol_upper:
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
