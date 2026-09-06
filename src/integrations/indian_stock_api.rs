/*
Lightweight Rust integration module for EQATS adapting the most reusable feature from 0xramm/Indian-Stock-Market-API: robust parsing/normalization of JSON quote responses (Yahoo/REST shapes).

Why this form: the original repository is a standalone JavaScript/Flask/Cloudflare worker REST service rather than an embeddable Rust/Python library. Embedding it requires running that external service. To provide a safe, testable, and immediately reusable component for EQATS we extract and adapt the normalization logic (turning heterogeneous JSON quote shapes into a canonical Quote struct). This is a zero-network module suitable for inclusion in the Rust core; networked fetching can be layered on top by EQATS' existing HTTP facilities.

This file is self-contained, compiles with serde/serde_json available, and includes unit tests that validate parsing behavior against representative JSON shapes produced by Yahoo-style APIs and lightweight REST responses.
*/

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Quote {
    pub symbol: String,
    pub price: f64,
    pub timestamp: Option<i64>,
    pub exchange: Option<String>,
}

/// Parse and normalize heterogeneous API responses into a canonical Quote.
/// The parser attempts multiple common shapes, including:
/// - { "quoteResponse": { "result": [ { ... } ] } }
/// - { "data": [...]} or { "result": [...] }
/// - top-level objects with fields like symbol, price, lastPrice, regularMarketPrice
pub fn parse_quote_from_api_response(s: &str) -> Result<Quote, serde_json::Error> {
    let v: Value = serde_json::from_str(s)?;

    // Try to find the most likely object that contains quote fields
    let candidate = if let Some(qr) = v.get("quoteResponse") {
        qr.get("result").and_then(|r| r.as_array()).and_then(|arr| arr.get(0)).cloned()
    } else if let Some(data) = v.get("data") {
        if data.is_array() {
            data.as_array().and_then(|arr| arr.get(0)).cloned()
        } else {
            Some(data.clone())
        }
    } else if let Some(res) = v.get("result") {
        res.as_array().and_then(|arr| arr.get(0)).cloned()
    } else {
        // fallback to top-level
        Some(v.clone())
    };

    let c = candidate.unwrap_or_else(|| Value::Object(serde_json::Map::new()));

    // helper to try multiple keys for a string field
    let get_str = |keys: &[&str]| -> Option<String> {
        for &k in keys {
            if let Some(val) = c.get(k) {
                if val.is_string() {
                    return val.as_str().map(|s| s.to_string());
                } else if val.is_number() {
                    // numeric symbol unlikely but convert
                    return Some(val.to_string());
                }
            }
        }
        None
    };

    // helper to try multiple keys for a numeric field
    let get_f64 = |keys: &[&str]| -> Option<f64> {
        for &k in keys {
            if let Some(val) = c.get(k) {
                if val.is_number() {
                    if let Some(f) = val.as_f64() { return Some(f); }
                } else if val.is_string() {
                    if let Some(s) = val.as_str() {
                        if let Ok(f) = s.parse::<f64>() { return Some(f); }
                    }
                }
            }
        }
        None
    };

    let symbol = get_str(&["symbol", "ticker", "s", "id"]).or_else(|| {
        // some APIs embed symbol under nested keys like "meta" -> "symbol"
        if let Some(meta) = c.get("meta") {
            if let Some(sym) = meta.get("symbol") {
                if sym.is_string() { return sym.as_str().map(|s| s.to_string()); }
            }
        }
        None
    });

    let price = get_f64(&[
        "regularMarketPrice",
        "lastPrice",
        "price",
        "currentPrice",
        "lTP",
        "ltp",
        "lastTradedPrice",
        "close",
    ]);

    let timestamp = (|| {
        for &k in &["regularMarketTime", "timestamp", "time", "lastUpdated"] {
            if let Some(val) = c.get(k) {
                if val.is_i64() { return val.as_i64(); }
                if val.is_u64() { return val.as_u64().map(|u| u as i64); }
                if val.is_number() { return val.as_f64().map(|f| f as i64); }
                if val.is_string() {
                    if let Some(s) = val.as_str() {
                        if let Ok(n) = s.parse::<i64>() { return Some(n); }
                    }
                }
            }
        }
        None
    })();

    let exchange = get_str(&["exchange", "exchangeName", "market"]);

    let symbol = symbol.unwrap_or_else(|| {
        // as a last ditch, try nested 'instrument' or use empty
        c.get("instrument").and_then(|ins| ins.get("symbol")).and_then(|v| v.as_str()).map(|s| s.to_string()).unwrap_or_else(|| "".to_string())
    });

    let price = price.unwrap_or(0.0);

    Ok(Quote {
        symbol,
        price,
        timestamp,
        exchange,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_quote_with_quote_response() {
        let json = r#"
        {
          "quoteResponse": {
            "result": [
              {
                "symbol": "TCS.NS",
                "regularMarketPrice": 3220.5,
                "regularMarketTime": 1625074800,
                "exchange": "NSE"
              }
            ],
            "error": null
          }
        }
        "#;

        let q = parse_quote_from_api_response(json).expect("parse should succeed");
        assert_eq!(q.symbol, "TCS.NS");
        assert!((q.price - 3220.5).abs() < 1e-6);
        assert_eq!(q.timestamp, Some(1625074800));
        assert_eq!(q.exchange.as_deref(), Some("NSE"));
    }

    #[test]
    fn test_parse_quote_with_top_level_simple() {
        let json = r#"{ "symbol": "RELIANCE.NS", "price": "2340.5" }"#;
        let q = parse_quote_from_api_response(json).expect("parse should succeed");
        assert_eq!(q.symbol, "RELIANCE.NS");
        assert!((q.price - 2340.5).abs() < 1e-6);
        assert_eq!(q.timestamp, None);
    }

    #[test]
    fn test_parse_quote_with_data_array() {
        let json = r#"
        { "data": [ { "ticker": "INFY.NS", "lastPrice": 1500.75, "market": "NSE" } ] }
        "#;
        let q = parse_quote_from_api_response(json).expect("parse should succeed");
        assert_eq!(q.symbol, "INFY.NS");
        assert!((q.price - 1500.75).abs() < 1e-6);
        assert_eq!(q.exchange.as_deref(), Some("NSE"));
    }
}
