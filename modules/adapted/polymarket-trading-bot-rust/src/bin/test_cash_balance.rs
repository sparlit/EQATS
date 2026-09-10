use anyhow::Result;
use clap::Parser;
use polymarket_trading_bot::{Config, PolymarketApi};
use rust_decimal::Decimal;

#[derive(Parser, Debug)]
#[command(name = "test_cash_balance")]
#[command(about = "Check Polymarket USD (pUSD) cash balance and allowance for your account")]
struct Args {
    /// Config file path
    #[arg(short, long, default_value = "config.json")]
    config: String,
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::Builder::from_default_env()
        .filter_level(log::LevelFilter::Info)
        .init();

    let args = Args::parse();
    let config_path = std::path::PathBuf::from(&args.config);
    let config = Config::load(&config_path)?;

    let api = PolymarketApi::from_config(&config);

    println!("🔍 Fetching pUSD (Polymarket USD) balance and allowance...\n");

    let (balance, allowance) = api.check_usdc_balance_allowance().await?;

    let one_million = Decimal::from(1_000_000u64);
    let balance_dollars = balance / one_million;
    let allowance_dollars = allowance / one_million;

    println!("   Cash (pUSD) balance:  ${:.2}", balance_dollars);
    println!("   pUSD allowance (to Exchange): ${:.2}", allowance_dollars);
    println!();

    Ok(())
}