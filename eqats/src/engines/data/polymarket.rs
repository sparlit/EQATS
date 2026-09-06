use serde::{Deserialize, Serialize};

/// Simple representation of a Polymarket market.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MarketData {
    pub id: String,
    pub question: String,
    pub best_bid: f64,
    pub best_ask: f64,
    pub volume: f64,
    pub timestamp: u64,
}

/// Polymarket data engine that fetches market data.
/// In a real implementation this would call the Polymarket REST/WebSocket APIs.
/// For demonstration and testability we return a static example.
pub struct PolymarketDataEngine;

impl PolymarketDataEngine {
    pub fn new() -> Self {
        Self
    }

    /// Fetch a list of markets.
    /// Returns a vector of MarketData.
    pub fn fetch_markets(&self) -> Vec<MarketData> {
        vec![MarketData {
            id: "0x1234".to_string(),
            question: "Will Bitcoin exceed $100k by end of 2025?".to_string(),
            best_bid: 0.62,
            best_ask: 0.66,
            volume: 12500.0,
            timestamp: 1_700_000_000,
        }]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fetch_markets_returns_data() {
        let engine = PolymarketDataEngine::new();
        let markets = engine.fetch_markets();
        assert!(!markets.is_empty(), "should return at least one market");
        let m = &markets[0];
        assert_eq!(m.id, "0x1234");
        assert!(m.best_bid < m.best_ask);
    }
}
