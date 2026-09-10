//! Query supply and borrow APY for a specific Morpho market.
//!
//! This example fetches both supply APY (what lenders earn) and borrow APY (what borrowers pay)
//! for a specific Morpho lending market. It's useful for lenders comparing yield opportunities
//! or building lending aggregators.
//!
//! # Usage
//!
//! ```bash
//! # Query APYs for a specific market
//! cargo run --example supply_apy -- \
//!   --market-id 0xabcd...1234 \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//!
//! # Custom IRM contract address
//! cargo run --example supply_apy -- \
//!   --contract-address 0x... \
//!   --market-id 0x... \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//! ```
//!
//! # What it does
//!
//! 1. Connects to HyperEVM via RPC
//! 2. Fetches market state from Morpho contract
//! 3. Queries Interest Rate Model (IRM) for current rates
//! 4. Calculates both supply and borrow APY
//! 5. Displays rates and last update timestamp
//!
//! # Output
//!
//! ```text
//! Connecting to RPC endpoint: https://rpc.hyperliquid.xyz/evm
//! market params last updated at 2024-01-08 12:34:56 UTC
//! borrow APY is 5.23
//! supply APY is 4.15
//! ```
//!
//! # Understanding APY
//!
//! - **Supply APY**: Rate earned by lenders (lower than borrow APY)
//! - **Borrow APY**: Rate paid by borrowers (higher than supply APY)
//! - **Spread**: Difference goes to protocol fees and reserves
//! - APY accounts for compound interest over a year

use alloy::primitives::FixedBytes;
use chrono::Utc;
use clap::Parser;
use hypersdk::{
    Address,
    hyperevm::{self, DynProvider},
};

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Cli {
    /// Address of the IRM contract.
    #[arg(
        short,
        long,
        default_value = "0xD4a426F010986dCad727e8dd6eed44cA4A9b7483"
    )]
    contract_address: Address,
    // Morpho market
    #[arg(short, long)]
    market_id: FixedBytes<32>,
    /// RPC url
    #[arg(short, long, default_value = "https://rpc.hyperliquid.xyz/evm")]
    rpc_url: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args = Cli::parse();

    println!("Connecting to RPC endpoint: {}", args.rpc_url);

    let provider = DynProvider::new(hyperevm::mainnet_with_url(&args.rpc_url).await?);
    let morpho = hyperevm::morpho::Client::new(provider.clone());
    let apy = morpho
        .apy::<f64, _>(args.contract_address, args.market_id, |e| e.exp())
        .await?;

    let last_update =
        chrono::DateTime::<Utc>::from_timestamp_secs(apy.market.lastUpdate as i64).unwrap();
    println!("market params last updated at {}", last_update);

    println!("borrow APY is {}", apy.borrow * 100.0);
    println!("supply APY is {}", apy.supply * 100.0);

    Ok(())
}