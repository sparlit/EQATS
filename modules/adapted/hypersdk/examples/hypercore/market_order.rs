//! Places a market buy or sell order.
//!
//! Demonstrates `market_open()` which uses Hyperliquid's native `FrontendMarket`
//! order type to fill immediately up to the provided worst acceptable price.

use clap::Parser;
use hypersdk::hypercore::{self as hypercore, NonceHandler};
use rust_decimal::Decimal;

use crate::credentials::Credentials;

mod credentials;

#[derive(Parser, Debug, derive_more::Deref)]
#[command(author, version, about, long_about = None)]
struct Cli {
    #[deref]
    #[command(flatten)]
    common: Credentials,

    /// Coin to trade (e.g. "ETH", "BTC")
    coin: String,

    /// Buy if true, sell if false
    #[arg(long, default_value_t = true)]
    buy: bool,

    /// Size in base asset units
    #[arg(long, default_value_t = 0.01_f64)]
    size: f64,

    /// Worst acceptable execution price
    #[arg(long)]
    price: Decimal,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _ = simple_logger::init_with_level(log::Level::Debug);

    let args = Cli::parse();
    let signer = args.get()?;

    let client = hypercore::testnet();
    let nonce_handler = NonceHandler::default();

    // Find the market
    let perps = client.perps().await?;
    let market = perps
        .iter()
        .find(|m| m.name == args.coin)
        .ok_or_else(|| anyhow::anyhow!("market '{}' not found", args.coin))?;

    let side = if args.buy { "buy" } else { "sell" };
    println!("Market {side} {} {} @ {}", args.coin, args.size, args.price);

    let statuses = client
        .market_open(
            &signer,
            market,
            args.buy,
            args.price,
            rust_decimal::Decimal::try_from(args.size).unwrap(),
            nonce_handler.next(),
            None,
            None,
            None,
        )
        .await?;

    for status in &statuses {
        match status {
            hypercore::OrderResponseStatus::Filled {
                avg_px,
                total_sz,
                oid,
            } => {
                println!("Filled #{oid}: {total_sz} @{avg_px}");
            }
            other => {
                println!("Status: {other:?}");
            }
        }
    }

    Ok(())
}