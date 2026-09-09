//! Query spot balances for a user on Hyperliquid.
//!
//! This example demonstrates how to retrieve all spot token balances including
//! standard tokens and outcome market positions.
//!
//! # Usage
//!
//! ```bash
//! cargo run --example user_balances -- <USER_ADDRESS>
//! ```

use clap::Parser;
use hypersdk::{Address, hypercore};

#[derive(Parser)]
struct Args {
    /// User address to query balances for
    user: Address,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args = Args::parse();
    let client = hypercore::mainnet();

    let balances = client.user_balances(args.user).await?;

    if balances.is_empty() {
        println!("No spot balances found for {:?}.", args.user);
        return Ok(());
    }

    println!("Spot balances for {:?}:", args.user);
    println!(
        "{:<12} {:>12} {:>12} {:>12}",
        "Coin", "Total", "Hold", "Available"
    );
    println!("{:-<48}", "");

    for balance in &balances {
        let available = balance.available();
        println!(
            "{:<12} {:>12} {:>12} {:>12}",
            balance.coin, balance.total, balance.hold, available
        );
    }

    Ok(())
}