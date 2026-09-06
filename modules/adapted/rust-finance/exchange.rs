use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone, Copy, PartialEq)]
pub enum ExchangeName {
    NYSE,
    NASDAQ,
    CME,
    CBOE,
    LSE,
    CRYPTO, // General crypto exchanges (e.g. Binance, Coinbase)
    NSE,
    BSE,
}

impl std::fmt::Display for ExchangeName {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ExchangeName::NYSE => write!(f, "NYSE"),
            ExchangeName::NASDAQ => write!(f, "NASDAQ"),
            ExchangeName::CME => write!(f, "CME"),
            ExchangeName::CBOE => write!(f, "CBOE"),
            ExchangeName::LSE => write!(f, "LSE"),
            ExchangeName::CRYPTO => write!(f, "CRYPTO"),
            ExchangeName::NSE => write!(f, "NSE"),
            ExchangeName::BSE => write!(f, "BSE"),
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Clone, Copy, PartialEq)]
pub enum ExchangeStatus {
    Connected,
    Degraded,
    Disconnected,
    Disabled,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ExchangeInfo {
    pub name: ExchangeName,
    pub status: ExchangeStatus,
    pub latency_ms: f64,
    pub last_heartbeat: Option<i64>,
}

impl ExchangeInfo {
    pub fn new(name: ExchangeName) -> Self {
        Self {
            name,
            status: ExchangeStatus::Disabled,
            latency_ms: 0.0,
            last_heartbeat: None,
        }
    }
}
