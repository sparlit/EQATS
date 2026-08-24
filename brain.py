import math

import config
import database
import indicators
import predictive_brain


def _get_symbol_pip_specs(symbol, current_price):
    """
    Returns (pip_size, pip_value_per_lot) tailored to asset class.
    Supports Forex Majors, Forex JPY Pairs, Gold/Metals, Crypto, and Equity Indices.
    """
    sym_upper = symbol.upper()
    if "XAU" in sym_upper or "GOLD" in sym_upper:
        return {"pip_size": 0.1, "pip_value_per_lot": 10.0}
    elif "XAG" in sym_upper or "SILVER" in sym_upper:
        return {"pip_size": 0.01, "pip_value_per_lot": 50.0}
    elif any(c in sym_upper for c in ["BTC", "ETH", "LTC", "SOL", "XRP", "DOGE", "ADA", "BNB", "DOT", "CRYPTO"]):
        return {"pip_size": 1.0, "pip_value_per_lot": 1.0}
    elif any(idx in sym_upper for idx in ["US30", "NAS100", "GER40", "DE40", "SPX500", "UK100", "JP225", "US500", "US100"]):
        return {"pip_size": 1.0, "pip_value_per_lot": 1.0}
    elif "JPY" in sym_upper:
        return {"pip_size": 0.01, "pip_value_per_lot": 6.5}
    else:
        # Standard FX Major / Minor
        return {"pip_size": 0.0001, "pip_value_per_lot": 10.0}


def _get_symbol_min_lot(symbol):
    """
    Returns default minimum lot size per asset class to prevent broker [Invalid volume] rejections.
    """
    sym_upper = symbol.upper()
    if "XRP" in sym_upper:
        return 1.0
    elif "LTC" in sym_upper or "SOL" in sym_upper:
        return 0.1
    elif any(idx in sym_upper for idx in ["US30", "NAS100", "GER40", "DE40", "SPX500"]):
        return 0.1
    else:
        return 0.01


class ScalperBrain:
    """
    The master decision engine. Analyzes historical price bar data,
    performs multi-timeframe analytics, evaluates trading strategies across regimes,
    computes dynamic asset-class position sizes, and returns actions with diagnostic telemetry.
    """

    def __init__(self):
        self.version = "3.2.1"

    def evaluate(self, symbol, history_bars, current_equity, brain_directive=None):
        """
        Analyzes historical bars and gives a decision: 'BUY', 'SELL', or 'HOLD'.
        history_bars: list of dicts/objects with keys: 'open', 'high', 'low', 'close'
        current_equity: float, current account balance/equity to calculate lot size.
        """
        min_bars_needed = max(
            getattr(config, "EMA_LONG_PERIOD", 200) + 10,
            getattr(config, "RSI_PERIOD", 14) + 10,
            getattr(config, "ATR_PERIOD", 14) + 10,
            getattr(config, "MACD_SLOW", 26) + 15,
        )

        if len(history_bars) < min_bars_needed:
            msg = f"Insufficient history data for {symbol}. Needs {min_bars_needed} bars, got {len(history_bars)}."
            database.log_assessment(symbol, "UNKNOWN", None, None, "HOLD", msg)
            return {
                "decision": "HOLD",
                "lot_size": 0.0,
                "sl": 0.0,
                "tp": 0.0,
                "explanation": msg,
                "indicators": {},
            }

        closes = [bar["close"] for bar in history_bars]
        highs = [bar["high"] for bar in history_bars]
        lows = [bar["low"] for bar in history_bars]

        current_price = closes[-1]

        # Calculate active indicators
        ema_long_period = min(getattr(config, "EMA_LONG_PERIOD", 200), len(closes) - 1)
        ema_long = indicators.calculate_ema(closes, ema_long_period)
        ema_short = indicators.calculate_ema(closes, getattr(config, "EMA_SHORT_PERIOD", 9))
        ema_medium = indicators.calculate_ema(closes, getattr(config, "EMA_MEDIUM_PERIOD", 21))
        rsi_val = indicators.calculate_rsi(closes, getattr(config, "RSI_PERIOD", 14))
        atr_val = indicators.calculate_atr(highs, lows, closes, getattr(config, "ATR_PERIOD", 14))
        bb = indicators.calculate_bollinger_bands(
            closes, getattr(config, "BB_PERIOD", 20), getattr(config, "BB_STD_DEV", 2.0)
        )
        macd = indicators.calculate_macd(
            closes, getattr(config, "MACD_FAST", 12), getattr(config, "MACD_SLOW", 26), getattr(config, "MACD_SIGNAL", 9)
        )

        if (
            ema_long is None
            or rsi_val is None
            or atr_val is None
            or ema_short is None
            or ema_medium is None
            or bb is None
            or macd is None
        ):
            msg = f"Indicator calculation returned None for {symbol} due to window constraints."
            database.log_assessment(symbol, "UNKNOWN", None, None, "HOLD", msg)
            return {
                "decision": "HOLD",
                "lot_size": 0.0,
                "sl": 0.0,
                "tp": 0.0,
                "explanation": msg,
                "indicators": {},
            }

        trend_direction = "UP" if current_price > ema_long else "DOWN"

        # --- Symbol Floating Loss Protection & Pyramiding Gate ---
        try:
            open_trades = database.get_open_trades()

            if len(open_trades) >= getattr(config, "MAX_CONCURRENT_TRADES", 10):
                msg = f"HOLD (Global Max Concurrent Trades Limit Reached: {len(open_trades)}/{getattr(config, 'MAX_CONCURRENT_TRADES', 10)})"
                database.log_assessment(symbol, trend_direction, rsi_val, atr_val, "HOLD", msg)
                return {
                    "decision": "HOLD",
                    "lot_size": 0.0,
                    "sl": 0.0,
                    "tp": 0.0,
                    "explanation": msg,
                    "indicators": {
                        "ema_long": round(ema_long, 5),
                        "rsi": round(rsi_val, 2),
                        "atr": round(atr_val, 5),
                    },
                }

            symbol_trades = [
                t for t in open_trades if t.get("symbol", "").upper() == symbol.upper()
            ]
            if symbol_trades:
                any_loss = False
                all_profit_1atr = True
                for t in symbol_trades:
                    direction = t.get("direction", "BUY")
                    trade_profit = t.get("profit")
                    open_price = float(t.get("open_price", current_price))
                    p_diff = (
                        (current_price - open_price)
                        if direction == "BUY"
                        else (open_price - current_price)
                    )

                    if trade_profit is not None:
                        is_losing = float(trade_profit) < 0
                    else:
                        is_losing = p_diff < 0

                    if is_losing:
                        any_loss = True
                        all_profit_1atr = False
                        break

                    if p_diff < atr_val:
                        all_profit_1atr = False

                if any_loss:
                    msg = f"HOLD (Symbol Floating Loss Protection Gate Active: open position on {symbol} in loss)"
                    database.log_assessment(symbol, trend_direction, rsi_val, atr_val, "HOLD", msg)
                    return {
                        "decision": "HOLD",
                        "lot_size": 0.0,
                        "sl": 0.0,
                        "tp": 0.0,
                        "explanation": msg,
                        "indicators": {
                            "ema_long": round(ema_long, 5),
                            "rsi": round(rsi_val, 2),
                            "atr": round(atr_val, 5),
                        },
                    }

                if not all_profit_1atr:
                    msg = f"HOLD (Pyramiding Gate: existing positions on {symbol} profit < 1.0x ATR threshold)"
                    database.log_assessment(symbol, trend_direction, rsi_val, atr_val, "HOLD", msg)
                    return {
                        "decision": "HOLD",
                        "lot_size": 0.0,
                        "sl": 0.0,
                        "tp": 0.0,
                        "explanation": msg,
                        "indicators": {
                            "ema_long": round(ema_long, 5),
                            "rsi": round(rsi_val, 2),
                            "atr": round(atr_val, 5),
                        },
                    }
        except Exception as e:
            print(f"Warning: Symbol floating loss check error: {e}")

        # --- AI Neural Predictor Integration ---
        predictor = predictive_brain.get_symbol_predictor(symbol)
        reg_info = indicators.classify_market_regime(highs, lows, closes)
        reg_state_val = 1.0 if reg_info["regime"] == "TRENDING" else 0.0

        baseline_atr = (
            sum(
                indicators.calculate_atr(highs[:i], lows[:i], closes[:i], 14) or atr_val
                for i in range(max(15, len(closes) - 20), len(closes))
            )
            / 20.0
        )
        vol_ratio = atr_val / baseline_atr if baseline_atr > 0 else 1.0

        rsi_norm = rsi_val / 100.0
        ema_ratio = ema_short / ema_medium if ema_medium > 0 else 1.0
        macd_ratio = macd["histogram"] / current_price if current_price > 0 else 0.0
        returns_prev = (closes[-1] - closes[-2]) / closes[-2] if len(closes) >= 2 else 0.0

        inputs = [rsi_norm, ema_ratio, macd_ratio, returns_prev, reg_state_val, vol_ratio]
        actual_bullish_close = 1.0 if closes[-1] > closes[-2] else 0.0
        predictor.learn_and_adjust(actual_bullish_close)

        ai_bullish_prob = predictor.predict(inputs)

        # 1. EVALUATE STRATEGY 1: TREND_FOLLOWING
        sig_tf = "HOLD"
        reasons_tf = []
        if trend_direction == "UP":
            if rsi_val <= 62.0 and ema_short > ema_medium:
                sig_tf = "BUY"
            else:
                if rsi_val > 62.0:
                    reasons_tf.append(f"RSI {rsi_val:.1f} overbought (>62)")
                if ema_short <= ema_medium:
                    reasons_tf.append("EMA-9 below EMA-21")
        else:
            if rsi_val >= 38.0 and ema_short < ema_medium:
                sig_tf = "SELL"
            else:
                if rsi_val < 38.0:
                    reasons_tf.append(f"RSI {rsi_val:.1f} oversold (<38)")
                if ema_short >= ema_medium:
                    reasons_tf.append("EMA-9 above EMA-21")

        # 2. EVALUATE STRATEGY 2: MEAN_REVERSION
        sig_mr = "HOLD"
        reasons_mr = []
        if current_price <= bb["lower"] and rsi_val <= 38.0:
            sig_mr = "BUY"
        elif current_price >= bb["upper"] and rsi_val >= 62.0:
            sig_mr = "SELL"
        else:
            if current_price > bb["lower"] and current_price < bb["upper"]:
                reasons_mr.append("Price inside Bands")

        # 3. EVALUATE STRATEGY 3: MACD_MOMENTUM
        sig_mac = "HOLD"
        if macd["histogram"] > 0 and macd["macd"] > macd["signal"]:
            sig_mac = "BUY"
        elif macd["histogram"] < 0 and macd["macd"] < macd["signal"]:
            sig_mac = "SELL"

        # 4. EVALUATE STRATEGY 4: BREAKOUT
        sig_bo = "HOLD"
        donchian = indicators.calculate_donchian_channels(
            highs, lows, getattr(config, "BREAKOUT_PERIOD", 20)
        )
        squeeze = indicators.calculate_bollinger_squeeze(
            closes, getattr(config, "BB_PERIOD", 20), getattr(config, "BB_STD_DEV", 2.0)
        )

        if donchian and squeeze is not None:
            if current_price >= donchian["upper"]:
                sig_bo = "BUY"
            elif current_price <= donchian["lower"]:
                sig_bo = "SELL"

        # 5. EVALUATE STRATEGY 5: CARRY_TRADE
        sig_cy = "HOLD"
        swap_val = getattr(config, "SWAP_LONG_POINTS", {}).get(symbol.upper(), 0.0)
        min_swap = getattr(config, "MIN_CARRY_YIELD_POINTS", 1.0)
        if abs(swap_val) >= min_swap:
            if swap_val > 0 and trend_direction == "UP" and rsi_val <= 60:
                sig_cy = "BUY"
            elif swap_val < 0 and trend_direction == "DOWN" and rsi_val >= 40:
                sig_cy = "SELL"

        # 6. EVALUATE STRATEGY 6: GRID_TRADE
        sig_gd = "HOLD"
        if rsi_val <= 40:
            sig_gd = "BUY"
        elif rsi_val >= 60:
            sig_gd = "SELL"

        # 7. EVALUATE STRATEGY 7: STAT_ARB
        sig_sa = "HOLD"
        try:
            ratio_series = [
                closes[j] / (closes[j - 1] if closes[j - 1] > 0 else 1.0)
                for j in range(max(1, len(closes) - 20), len(closes))
            ]
            mean_r = sum(ratio_series) / len(ratio_series)
            var_r = sum((x - mean_r) ** 2 for x in ratio_series) / len(ratio_series)
            std_r = math.sqrt(var_r) if var_r > 0 else 0.001

            curr_ratio = closes[-1] / (closes[-2] if closes[-2] > 0 else 1.0)
            z_score = (curr_ratio - mean_r) / std_r

            if z_score <= -1.8:
                sig_sa = "BUY"
            elif z_score >= 1.8:
                sig_sa = "SELL"
        except Exception:
            sig_sa = "HOLD"

        # 8. EVALUATE STRATEGY 8: ORB
        sig_or = "HOLD"
        lookback_orb = min(30, len(closes) - 1)
        if lookback_orb >= 10:
            open_high = max(highs[:lookback_orb])
            open_low = min(lows[:lookback_orb])
            if current_price > open_high:
                sig_or = "BUY"
            elif current_price < open_low:
                sig_or = "SELL"

        # 9. EVALUATE STRATEGY 9: VSA
        sig_vs = "HOLD"
        vsa_res = indicators.calculate_vsa_metrics(highs, lows, closes)
        if vsa_res["vsa_bias"] == "ACCUMULATION" and current_price < ema_long:
            sig_vs = "BUY"
        elif vsa_res["vsa_bias"] == "DISTRIBUTION" and current_price > ema_long:
            sig_vs = "SELL"

        # 10. EVALUATE STRATEGY 10: MTF_CONFLUENCE
        sig_mtf = "HOLD"
        try:
            sma20 = sum(closes[-20:]) / 20.0
            sma50 = sum(closes[-min(50, len(closes)):]) / float(min(50, len(closes)))
            sma100 = sum(closes[-min(100, len(closes)):]) / float(min(100, len(closes)))

            rsi10 = indicators.calculate_rsi(closes, 10) or 50.0
            rsi14 = rsi_val
            rsi21 = indicators.calculate_rsi(closes, 21) or 50.0

            bullish_count = 0
            bearish_count = 0

            for p in [sma20, sma50, sma100]:
                if current_price > p:
                    bullish_count += 1
                else:
                    bearish_count += 1

            for r in [rsi10, rsi14, rsi21]:
                if r > 50:
                    bullish_count += 1
                else:
                    bearish_count += 1

            if bullish_count >= 5:
                sig_mtf = "BUY"
            elif bearish_count >= 5:
                sig_mtf = "SELL"
        except Exception:
            sig_mtf = "HOLD"

        # SMC / ICT Strategy
        smc_data = indicators.get_smc_analysis(history_bars)
        sig_smc = (
            "BUY" if smc_data["bias"] == "BULLISH"
            else ("SELL" if smc_data["bias"] == "BEARISH" else "HOLD")
        )

        # Order Flow & Microstructure Strategy
        order_book_data = getattr(config, "CURRENT_ORDER_BOOK", None)
        of_metrics = indicators.calculate_order_flow_metrics(history_bars, order_book=order_book_data)
        sig_of = "HOLD"
        if not of_metrics["is_toxic_flow"]:
            if of_metrics["dominant_side"] == "BUY_DOMINANT" or of_metrics["expected_direction"] == "UPWARD_PRESSURE":
                sig_of = "BUY"
            elif of_metrics["dominant_side"] == "SELL_DOMINANT" or of_metrics["expected_direction"] == "DOWNWARD_PRESSURE":
                sig_of = "SELL"

        strategy_mode = getattr(config, "ACTIVE_STRATEGY", "VOTING_ENSEMBLE")
        decision = "HOLD"
        explanation = ""

        reg_state = reg_info["regime"]

        if strategy_mode == "TREND_FOLLOWING":
            decision = sig_tf
            explanation = f"Trend Setup: {decision}"
        elif strategy_mode == "MEAN_REVERSION":
            decision = sig_mr
            explanation = f"Mean Reversion Setup: {decision}"
        elif strategy_mode == "MACD_MOMENTUM":
            decision = sig_mac
            explanation = f"MACD Setup: {decision}"
        elif strategy_mode == "BREAKOUT":
            decision = sig_bo
            explanation = f"Breakout Setup: {decision}"
        elif strategy_mode == "CARRY_TRADE":
            decision = sig_cy
            explanation = f"Carry Trade: {decision}"
        elif strategy_mode == "GRID_TRADE":
            decision = sig_gd
            explanation = f"Grid Placement Bias: {decision}"
        elif strategy_mode == "STAT_ARB":
            decision = sig_sa
            explanation = f"StatArb Setup: {decision}"
        elif strategy_mode == "ORB":
            decision = sig_or
            explanation = f"ORB Setup: {decision}"
        elif strategy_mode == "VSA":
            decision = sig_vs
            explanation = f"VSA Setup: {decision}"
        elif strategy_mode == "MTF_CONFLUENCE":
            decision = sig_mtf
            explanation = f"MTF Confluence: {decision}"
        elif strategy_mode == "SMC_ICT":
            decision = sig_smc
            explanation = f"SMC/ICT Structure: {decision} | Confluence: {smc_data['confluence_score']}%"
        elif strategy_mode == "ORDER_FLOW":
            decision = sig_of
            explanation = f"Order Flow Microstructure: {decision} | VPIN: {of_metrics['vpin']}"
        else:  # VOTING_ENSEMBLE
            sig_to_val = lambda s: 1.0 if s == "BUY" else (-1.0 if s == "SELL" else 0.0)

            tf_val = sig_to_val(sig_tf)
            mr_val = sig_to_val(sig_mr)
            mac_val = sig_to_val(sig_mac)
            bo_val = sig_to_val(sig_bo)
            cy_val = sig_to_val(sig_cy)
            sa_val = sig_to_val(sig_sa)
            or_val_v = sig_to_val(sig_or)
            vs_val = sig_to_val(sig_vs)
            mtf_val = sig_to_val(sig_mtf)
            smc_val = sig_to_val(sig_smc)
            of_val = sig_to_val(sig_of)

            # Regime-dependent strategy weighting
            if reg_state == "TRENDING":
                tf_w, mr_w, mac_w, bo_w, cy_w, sa_w, or_w, vs_w, mtf_w, smc_w, of_w = (
                    3.0, 0.0, 1.5, 2.5, 0.5, 0.0, 1.5, 1.5, 2.0, 2.0, 2.0
                )
            else:  # RANGING
                tf_w, mr_w, mac_w, bo_w, cy_w, sa_w, or_w, vs_w, mtf_w, smc_w, of_w = (
                    0.0, 3.0, 1.0, 0.0, 0.5, 2.5, 0.5, 2.0, 1.0, 2.0, 2.5
                )

            total_weight = (
                tf_w + mr_w + mac_w + bo_w + cy_w + sa_w + or_w + vs_w + mtf_w + smc_w + of_w
            )
            weighted_score = (
                (tf_val * tf_w)
                + (mr_val * mr_w)
                + (mac_val * mac_w)
                + (bo_val * bo_w)
                + (cy_val * cy_w)
                + (sa_val * sa_w)
                + (or_val_v * or_w)
                + (vs_val * vs_w)
                + (mtf_val * mtf_w)
                + (smc_val * smc_w)
                + (of_val * of_w)
            )

            normalized_score = (
                weighted_score / total_weight if total_weight > 0 else 0.0
            )

            if normalized_score >= 0.22:
                if ai_bullish_prob >= 0.35:
                    decision = "BUY"
                    explanation = f"Regime Consensus BUY ({reg_info['detailed_regime']}) | Score: {normalized_score:.2f} | AI Bullish Prob: {ai_bullish_prob:.2f}"
                else:
                    decision = "HOLD"
                    explanation = f"BUY Vetoed: AI strongly bearish ({ai_bullish_prob:.2f}) | Score: {normalized_score:.2f}"
            elif normalized_score <= -0.22:
                if ai_bullish_prob <= 0.65:
                    decision = "SELL"
                    explanation = f"Regime Consensus SELL ({reg_info['detailed_regime']}) | Score: {normalized_score:.2f} | AI Bullish Prob: {ai_bullish_prob:.2f}"
                else:
                    decision = "HOLD"
                    explanation = f"SELL Vetoed: AI strongly bullish ({ai_bullish_prob:.2f}) | Score: {normalized_score:.2f}"
            else:
                decision = "HOLD"
                explanation = f"Regime {reg_info['detailed_regime']} Neutral hold (Score: {normalized_score:+.2f})"

        # Macro NLP Veto Filter
        try:
            prevailing_sentiment = database.get_prevailing_news_sentiment()
            if prevailing_sentiment == "BULLISH" and decision == "SELL":
                decision = "HOLD"
                explanation = f"HOLD (Macro Vetoed: News Sentiment BULLISH) | {explanation}"
            elif prevailing_sentiment == "BEARISH" and decision == "BUY":
                decision = "HOLD"
                explanation = f"HOLD (Macro Vetoed: News Sentiment BEARISH) | {explanation}"
        except Exception as e:
            print(f"Warning: News sentiment filter error: {e}")

        # --- Dynamic Hybrid Volatility & Structure SL/TP ---
        sl = 0.0
        tp = 0.0
        lot_size = 0.0

        style_mode = getattr(config, "TRADING_STYLE", "SCALPING")
        style_multiplier = 1.5
        style_target_rr = getattr(config, "RISK_REWARD_RATIO", 1.5)

        if style_mode == "DAY_TRADING":
            style_multiplier = 2.5
            style_target_rr = 2.0
        elif style_mode == "SWING_TRADING":
            style_multiplier = 4.0
            style_target_rr = 3.0
        elif style_mode == "POSITION_TRADING":
            style_multiplier = 6.0
            style_target_rr = 4.5

        volatility_ratio = atr_val / baseline_atr if baseline_atr > 0 else 1.0
        adaptive_rr = style_target_rr * (1.25 if volatility_ratio > 1.2 else (0.85 if volatility_ratio < 0.8 else 1.0))

        swings = indicators.calculate_swing_points(highs, lows, window=2)
        swing_high = swings.get("last_swing_high")
        swing_low = swings.get("last_swing_low")

        base_sl_dist = atr_val * style_multiplier

        if decision == "BUY":
            struct_sl = swing_low if (swing_low and swing_low < current_price) else (current_price - base_sl_dist)
            sl_dist = current_price - struct_sl
            sl_dist = max(atr_val * 1.0, min(atr_val * 3.5, sl_dist))
            sl = current_price - sl_dist
            tp = current_price + (sl_dist * adaptive_rr)
            lot_size = self._calculate_lot_size(symbol, current_equity, sl_dist, current_price)
        elif decision == "SELL":
            struct_sl = swing_high if (swing_high and swing_high > current_price) else (current_price + base_sl_dist)
            sl_dist = struct_sl - current_price
            sl_dist = max(atr_val * 1.0, min(atr_val * 3.5, sl_dist))
            sl = current_price + sl_dist
            tp = current_price - (sl_dist * adaptive_rr)
            lot_size = self._calculate_lot_size(symbol, current_equity, sl_dist, current_price)

        # Multi-Agent Brain Directive Modifiers
        if brain_directive is None:
            try:
                from brain_agents_orchestrator import global_brain_orchestrator
                brain_directive = global_brain_orchestrator.last_directive
            except Exception:
                brain_directive = None

        if brain_directive and hasattr(brain_directive, "guidance_notes") and brain_directive.guidance_notes:
            explanation += f" | Agents: {'; '.join(brain_directive.guidance_notes[:2])}"

        database.log_assessment(
            symbol=symbol,
            trend_direction=trend_direction,
            rsi_val=rsi_val,
            atr_val=atr_val,
            decision=decision,
            explanation=explanation,
        )

        return {
            "decision": decision,
            "lot_size": round(lot_size, 2),
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "explanation": explanation,
            "indicators": {
                "ema_long": round(ema_long, 5),
                "rsi": round(rsi_val, 2),
                "atr": round(atr_val, 5),
            },
        }

    def normalize_volume(self, symbol, volume, min_vol=0.01, max_vol=100.0, step_vol=0.01):
        """Normalizes lot size according to minimum volume, maximum volume, and volume step."""
        if volume <= 0:
            return min_vol
        norm_vol = max(min_vol, min(max_vol, float(volume)))
        if step_vol > 0:
            steps = round((norm_vol - min_vol) / step_vol)
            calc_vol = min_vol + steps * step_vol
            step_str = f"{step_vol:.8f}".rstrip("0")
            precision = len(step_str.split(".")[1]) if "." in step_str else 0
            norm_vol = round(calc_vol, precision)
            norm_vol = max(min_vol, min(max_vol, norm_vol))
        return norm_vol

    def _calculate_lot_size(self, symbol, equity, sl_distance, current_price=1.0):
        """
        Calculates dynamic position size using Fractional Kelly / ATR Volatility Sizing.
        Dynamic pip calculations accurately adapt across Forex, Metals, Crypto, and Equity Indices.
        Enforces asset-class minimum lot floors (e.g. 0.1 for LTC, 1.0 for XRP) to prevent broker rejection.
        """
        min_lot = _get_symbol_min_lot(symbol)

        if getattr(config, "FIXED_LOT_SIZE_ONLY", True):
            return min_lot

        if equity <= 0 or sl_distance <= 0:
            return min_lot

        try:
            risk_pct = getattr(config, "RISK_PER_TRADE_PERCENT", 1.0) / 100.0
            risk_amount = equity * risk_pct

            pip_specs = _get_symbol_pip_specs(symbol, current_price)
            pip_size = pip_specs["pip_size"]
            pip_val_per_lot = pip_specs["pip_value_per_lot"]

            sl_pips = sl_distance / pip_size if pip_size > 0 else 10.0
            sl_pips = max(5.0, sl_pips)

            raw_lots = risk_amount / (sl_pips * pip_val_per_lot)

            # Fractional Kelly Scaling Factor (0.25)
            kelly_lots = raw_lots * 0.25

            max_lot = getattr(config, "MAX_LOT_SIZE", 5.0)
            lot_size = self.normalize_volume(symbol, kelly_lots, min_vol=0.01, max_vol=max_lot, step_vol=0.01)
            return lot_size
        except Exception:
            return min_lot
