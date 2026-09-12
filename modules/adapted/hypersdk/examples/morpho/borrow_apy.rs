//! Query borrow APY for a specific Morpho market.
//!
//! This example fetches the current borrow APY (Annual Percentage Yield) for a specific
//! Morpho lending market. It's useful for borrowers looking to compare rates or build
//! lending rate comparison tools.
//!
//! # Usage
//!
//! ```bash
//! # Query borrow APY for a specific market
//! cargo run --example borrow_apy -- \
//!   --market-id 0xabcd...1234 \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//!
//! # Custom Morpho contract address
//! cargo run --example borrow_apy -- \
//!   --contract-address 0x... \
//!   --market-id 0x... \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//! ```
//!
//! # What it does
//!
//! 1. Connects to HyperEVM via RPC
//! 2. Fetches market parameters and state from Morpho contract
//! 3. Calculates current borrow APY based on utilization and IRM
//! 4. Resolves collateral and loan token symbols
//! 5. Displays borrow rate and last update timestamp
//!
//! # Output
//!
//! ```text
//! Connecting to RPC endpoint: https://rpc.hyperliquid.xyz/evm
//! market params last updated at 2024-01-08 12:34:56 UTC
//! borrow APY for USDC / WETH is 5.23
//! ```
//!
//! # Finding Market IDs
//!
//! Market IDs can be found by:
//! - Using the `create_market_events` example to list all markets
//! - Querying Morpho subgraphs or indexers
//! - Checking Morpho documentation for specific market IDs

use alloy::{primitives::FixedBytes, providers::Provider};
use chrono::Utc;
use clap::Parser;
use hypersdk::{
    Address, Decimal,
    hyperevm::{self, DynProvider, ERC20},
};
use rust_decimal::MathematicalOps;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Cli {
    /// Address of the morpho contract
    #[arg(
        short,
        long,
        default_value = "0x68e37dE8d93d3496ae143F2E900490f6280C57cD"
    )]
    contract_address: Address,
    // Morpho market
    #[arg(short, long)]
    market_id: FixedBytes<32>,
    /// RPC url
    #[arg(short, long, default_value = "http://127.0.0.1:8545")]
    rpc_url: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args = Cli::parse();

    println!("Connecting to RPC endpoint: {}", args.rpc_url);

    let provider = DynProvider::new(hyperevm::mainnet_with_url(&args.rpc_url).await?);
    let morpho = hyperevm::morpho::Client::new(provider.clone());
    let apy = morpho
        .apy::<Decimal, _>(args.contract_address, args.market_id, |e| e.exp())
        .await?;

    let last_update =
        chrono::DateTime::<Utc>::from_timestamp_secs(apy.market.lastUpdate as i64).unwrap();
    println!("market params last updated at {}", last_update);

    let market_params = &apy.params;
    let (collateral, loan) = provider
        .multicall()
        .add(ERC20::new(market_params.collateralToken, provider.clone()).symbol())
        .add(ERC20::new(market_params.loanToken, provider.clone()).symbol())
        .aggregate()
        .await?;

    println!(
        "borrow APY for {loan} / {collateral} is {}",
        apy.borrow * Decimal::ONE_HUNDRED
    );

    Ok(())
}