use std::error::Error;

#[derive(Debug, Clone)]
pub struct Quote {
    pub close: f64,
    pub prev_close: f64,
    pub open: f64,
    pub volume: f64,
    pub avg_volume_3_months: f64,
    pub market_cap: f64,
    pub monthly_5_years: f64,
    pub pe_ratio: f64,
    pub eps_ratio: f64,
}

pub fn get_quote(_exchange: &str, _symbol: &str) -> Result<Quote, Box<dyn Error>> {
    Err("Scraping Yahoo Finance is not implemented due to site volatility and need for up-to-date selectors".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_get_quote_returns_error() {
        let res = get_quote("NSE", "NTPC");
        assert!(res.is_err());
    }
}