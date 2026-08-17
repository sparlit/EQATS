"""
Institutional Web Services and API Core.
Integrates FastAPI, Flask, Robyn, Kafka, Airflow, CCXT, and yFinance.

SECURITY FIX: The fetch_yfinance_external_rates function previously had a fallback
to mock data. This has been removed. If yfinance is not available, the function
now returns an error rather than fabricated data. Real external data feeds must be
properly implemented for production use.

DATA VALIDATION: External data is now validated for quality, freshness, completeness,
and consistency before being returned for use in trading decisions.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_validator import get_data_validator

def fetch_yfinance_external_rates(symbol, period="1mo", interval="1d"):
    """
    Pulls historical spot prices directly from Yahoo Finance API (yFinance).
    
    SECURITY FIX: Mock fallback removed. If yfinance is not available, returns
    error instead of fabricated data. Implement real external data feeds for production.
    
    DATA VALIDATION: Validates fetched data for quality, freshness, completeness,
    and consistency before returning.
    """
    try:
        import yfinance as yf
        from datetime import datetime as dt
        
        ticker_map = {
            "EURUSD": "EURUSD=X",
            "GBPUSD": "GBPUSD=X",
            "USDJPY": "JPY=X",
            "BTCUSD": "BTC-USD",
            "ETHUSD": "ETH-USD"
        }
        yf_symbol = ticker_map.get(symbol.upper(), symbol)
        data = yf.download(yf_symbol, period=period, interval=interval, progress=False)
        closes = data['Close'].tolist()
        
        # Validate data quality
        validator = get_data_validator()
        validation = validator.validate_prices(closes, symbol)
        
        if not validation['valid']:
            return {
                "status": "ERROR",
                "error": "Data validation failed",
                "validation_errors": validation['errors'],
                "validation_warnings": validation['warnings'],
                "quality_score": validation['score'],
                "note": "Fetched data failed quality validation"
            }
        
        # Return validated data with metadata
        return {
            "status": "SUCCESS",
            "data": [float(c) for c in closes],
            "symbol": symbol,
            "quality_score": validation['score'],
            "validation_warnings": validation['warnings'],
            "data_points": len(closes),
            "source": "yfinance"
        }
        
    except ImportError:
        return {
            "status": "ERROR",
            "error": "yfinance library not installed",
            "note": "Install yfinance: pip install yfinance"
        }
    except Exception as e:
        return {
            "status": "ERROR",
            "error": f"Failed to fetch data from yfinance: {str(e)}",
            "note": "Check symbol and network connection"
        }


def push_telemetry_to_kafka_queue(topic, payload_dict):
    """
    Pipes real-time trade execution details onto Apache Kafka messaging queues.
    """
    try:
        from kafka import KafkaProducer
        import json
        producer = KafkaProducer(
            bootstrap_servers=['localhost:9092'],
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        producer.send(topic, payload_dict)
        return True
    except ImportError:
        return False
