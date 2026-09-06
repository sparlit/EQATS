use soroban_sdk::{Env, Address};

use stellar_escrow_contract::StellarEscrowClient;

#[derive(Debug, Clone)]
pub struct TradeMetrics {
    pub volume: u128,
    pub success_rate: f64,
    pub unique_addresses: u32,
    pub window_start: u64,
    pub window_end: u64,
}

pub fn fetch_trade_metrics(
    env: &Env,
    contract_address: &Address,
    window_start: u64,
    window_end: u64,
) -> Result<TradeMetrics, Box<dyn std::error::Error>> {
    let client = StellarEscrowClient::new(env, contract_address);
    let (volume, success_rate_bp, unique_addrs, ws, we) = client.analytics_query(&window_start, &window_end);
    Ok(TradeMetrics {
        volume,
        success_rate: success_rate_bp as f64 / 100.0,
        unique_addresses: unique_addrs,
        window_start: ws,
        window_end: we,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use soroban_sdk::{Env, Address};

    #[test]
    fn test_fetch_trade_metrics_signature() {
        let env = Env::default();
        let contract_addr = Address::generate(&env);
        let res = std::panic::catch_unwind(|| {
            fetch_trade_metrics(&env, &contract_addr, 0, 1000)
        });
        assert!(res.is_ok());
    }
}