use anyhow::Result;
use crossbeam_channel::Sender;
use rand::Rng;
use rand_distr::{Distribution, Normal};
use serde_json::json;
use tracing::{info, warn, debug};
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::time::{interval, Duration};

pub struct SyntheticMarket {
    symbol: String,
    price: f64,
    volatility: f64,
    drift: f64,
}

impl SyntheticMarket {
    pub fn new(symbol: &str, initial_price: f64, volatility: f64, drift: f64) -> Self {
        Self {
            symbol: symbol.to_string(),
            price: initial_price,
            volatility,
            drift,
        }
    }

    /// Geometric Brownian Motion step
    pub fn step(&mut self, dt: f64) -> f64 {
        let mut rng = rand::thread_rng();
        let normal = Normal::new(0.0, 1.0).unwrap();
        let z = normal.sample(&mut rng);
        
        let drift_term = (self.drift - 0.5 * self.volatility.powi(2)) * dt;
        let vol_term = self.volatility * dt.sqrt() * z;
        
        self.price *= (drift_term + vol_term).exp();
        self.price
    }
}

pub struct MockIngestionService {
    tx: Sender<String>,
}

impl MockIngestionService {
    pub fn new(tx: Sender<String>) -> Self {
        Self { tx }
    }

    pub async fn run(&self) -> Result<()> {
        info!("Synthetic Tick Generator starting... (Simulating live market data)");
        
        // Setup synthetic markets
        let mut markets = vec![
            SyntheticMarket::new("AAPL", 150.0, 0.2, 0.05),
            SyntheticMarket::new("MSFT", 300.0, 0.15, 0.08),
            SyntheticMarket::new("TSLA", 200.0, 0.4, 0.02),
        ];

        // 100ms tick rate (10 ticks per second)
        let dt = 1.0 / 252.0 / 6.5 / 60.0 / 60.0 / 10.0; // Trading year fraction per 100ms
        let mut ticker = interval(Duration::from_millis(100));
        
        loop {
            ticker.tick().await;
            
            for market in &mut markets {
                let current_price = market.step(dt);
                
                // Format roughly matching what Finnhub WS produces, 
                // but wrapped so the router can digest it
                let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis();
                
                // Generate a random trade volume
                let mut rng = rand::thread_rng();
                let vol: f64 = rng.gen_range(10.0..500.0);
                
                let mock_trade = json!({
                    "data": [{
                        "p": current_price,
                        "s": market.symbol,
                        "t": timestamp,
                        "v": vol
                    }],
                    "type": "trade"
                });

                if let Err(e) = self.tx.try_send(mock_trade.to_string()) {
                    warn!("Mock tx channel saturated/closed: {:?}", e);
                    return Ok(());
                } else {
                    debug!("Synthetic tick: {} @ {:.2}", market.symbol, current_price);
                }
            }
        }
    }
}