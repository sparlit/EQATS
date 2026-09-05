/// Quick validation — just checks format, not live API calls
pub fn validate_key_format(name: &str, value: &str) -> Result<(), String> {
    match name {
        "FINNHUB_API_KEY" => {
            if value.len() < 10 {
                return Err("Finnhub keys are typically 20+ characters".into());
            }
        }
        "ALPACA_API_KEY" => {
            if !value.starts_with("AK") && !value.starts_with("PK") {
                return Err("Alpaca Key IDs typically start with AK or PK".into());
            }
        }
        "ALPACA_SECRET_KEY" => {
            if value.len() < 20 {
                return Err("Alpaca secret keys are typically 40+ characters".into());
            }
        }
        "ANTHROPIC_API_KEY" => {
            if !value.starts_with("sk-ant-") {
                return Err("Anthropic keys start with sk-ant-".into());
            }
        }
        _ => {}
    }
    Ok(())
}
