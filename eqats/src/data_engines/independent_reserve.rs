use serde::{Deserialize, Serialize};
use std::error::Error;
use reqwest::blocking::Client;

#[derive(Debug, Deserialize, Serialize)]
pub struct OrderBook {
    pub bids: Vec<(f64, f64)>,
    pub asks: Vec<(f64, f64)>,
}

pub trait ExchangeDataEngine {
    fn get_orderbook(&self) -> Result<OrderBook, Box<dyn Error>>;
}

pub struct IndependentReserveClient {
    client: Client,
    base_url: String,
}

impl IndependentReserveClient {
    pub fn new() -> Self {
        Self {
            client: Client::new(),
            base_url: "https://api.independentreserve.com".to_string(),
        }
    }
}

impl ExchangeDataEngine for IndependentReserveClient {
    fn get_orderbook(&self) -> Result<OrderBook, Box<dyn Error>> {
        let url = format!("{}/Public/GetOrderBook?xbtUsd=1", self.base_url);
        let resp = self.client.get(&url).send()?;
        if !resp.status().is_success() {
            return Err(format!("HTTP {}", resp.status()).into());
        }
        let ob: OrderBook = resp.json()?;
        Ok(ob)
    }
}

pub fn calculate_spread(ob: &OrderBook) -> f64 {
    let best_bid = ob.bids.first().map(|(price, _)| *price).unwrap_or(0.0);
    let best_ask = ob.asks.first().map(|(price, _)| *price).unwrap_or(0.0);
    if best_bid > 0.0 && best_ask > 0.0 {
        best_ask - best_bid
    } else {
        0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;

    struct MockHttpClient {
        response_body: Vec<u8>,
    }

    impl MockHttpClient {
        fn new(body: &str) -> Self {
            Self {
                response_body: body.as_bytes().to_vec(),
            }
        }
    }

    struct MockExchangeDataEngine {
        orderbook: OrderBook,
    }

    impl ExchangeDataEngine for MockExchangeDataEngine {
        fn get_orderbook(&self) -> Result<OrderBook, Box<dyn Error>> {
            Ok(self.orderbook.clone())
        }
    }

    #[test]
    fn test_spread_calculation() {
        let ob = OrderBook {
            bids: vec![(100.0, 1.5), (99.0, 2.0)],
            asks: vec![(101.0, 1.0), (102.0, 2.5)],
        };
        let spread = calculate_spread(&ob);
        assert_eq!(spread, 1.0);
    }

    #[test]
    fn test_mock_exchange() {
        let ob = OrderBook {
            bids: vec![(150.0, 0.5)],
            asks: vec![(151.0, 0.5)],
        };
        let mock = MockExchangeDataEngine { orderbook: ob.clone() };
        let fetched = mock.get_orderbook().expect("failed");
        assert_eq!(fetched.bids, ob.bids);
        assert_eq!(fetched.asks, ob.asks);
    }
}
