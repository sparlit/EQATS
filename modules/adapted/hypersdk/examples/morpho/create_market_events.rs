//! List all Morpho markets with their current state.
//!
//! This example scans the entire blockchain for Morpho CreateMarket events and displays
//! detailed information about each lending market including collateral, loan tokens,
//! borrowed/supplied amounts, and risk parameters. Useful for market research and
//! building lending protocol dashboards.
//!
//! # Usage
//!
//! ```bash
//! # List all Morpho markets
//! cargo run --example create_market_events -- \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//!
//! # Custom Morpho contract
//! cargo run --example create_market_events -- \
//!   --contract-address 0x... \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//! ```
//!
//! # What it does
//!
//! 1. Connects to HyperEVM via RPC
//! 2. Scans blockchain for all CreateMarket events (with progress bar)
//! 3. Resolves token symbols for collateral and loan tokens
//! 4. Fetches current market state (borrowed/supplied amounts)
//! 5. Sorts markets by total borrowed amount
//! 6. Displays comprehensive market details
//!
//! # Output
//!
//! ```text
//! ------------
//! market: 0xabcd...1234
//! collateral: WETH
//! loan token: USDC
//! oracle: 0x5678...
//! irm: 0x9abc...
//! LLTV: 860000000000000000
//! borrowed: 1000000000000
//! supplied: 2000000000000
//! ```
//!
//! # Market Parameters
//!
//! - **LLTV**: Liquidation Loan-to-Value ratio (e.g., 0.86 = 86%)
//! - **IRM**: Interest Rate Model contract address
//! - **Oracle**: Price oracle contract for collateral valuation
//! - **Borrowed/Supplied**: Current market utilization
//!
//! The example uses concurrent fetching with dynamic rate limiting for optimal performance.

use std::{sync::Arc, time::Duration};

use alloy::{primitives::FixedBytes, providers::Provider, rpc::types::Filter, sol_types::SolEvent};
use clap::Parser;
use hypersdk::{
    Address, U256,
    hyperevm::{
        self, DynProvider, ERC20,
        morpho::contracts::{IMorpho, MorphoEvents},
    },
};
use indicatif::ProgressBar;
use tokio::{
    sync::{Semaphore, mpsc::unbounded_channel},
    time::sleep,
};

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Cli {
    /// The address of the morpho vault.
    #[arg(
        short,
        long,
        default_value = "0x68e37dE8d93d3496ae143F2E900490f6280C57cD"
    )]
    contract_address: Address,
    /// RPC url
    #[arg(short, long, default_value = "http://127.0.0.1:8545")]
    rpc_url: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _ = simple_logger::init_with_level(log::Level::Info);
    let args = Cli::parse();

    println!("Connecting to RPC endpoint: {}", args.rpc_url);

    let provider = DynProvider::new(hyperevm::mainnet_with_url(&args.rpc_url).await?);
    let current_block = provider.get_block_number().await?;

    #[derive(PartialEq, Eq, PartialOrd, Ord)]
    struct MarketParams {
        id: FixedBytes<32>,
        collateral_token: String,
        loan_token: String,
        irm: Address,
        oracle: Address,
        lltv: U256,
    }

    let bar = ProgressBar::new(current_block);
    let semaphore = Arc::new(Semaphore::new(8));
    let (tx, mut rx) = unbounded_channel();
    for from_block in (0..current_block).step_by(100_000) {
        let provider = provider.clone();
        let tx = tx.clone();

        let to_block = (from_block + 100_000).min(current_block);
        let filter = Filter::new()
            .address(args.contract_address)
            .event_signature(MorphoEvents::CreateMarket::SIGNATURE_HASH)
            .from_block(from_block)
            .to_block(to_block);

        let bar = bar.clone();
        let semaphore = Arc::clone(&semaphore);
        tokio::spawn(async move {
            let _permit = semaphore.acquire().await?;
            let logs = provider.get_logs(&filter).await?;
            bar.inc(to_block - from_block);
            for log in logs {
                let Some(topic0) = log.topic0() else {
                    continue;
                };

                if topic0 == &MorphoEvents::CreateMarket::SIGNATURE_HASH {
                    if let Ok(market) = MorphoEvents::CreateMarket::decode_log_data(&log.inner) {
                        let collateral =
                            ERC20::new(market.marketParams.collateralToken, provider.clone());
                        let loan = ERC20::new(market.marketParams.loanToken, provider.clone());
                        let (collateral, loan) = provider
                            .multicall()
                            .add(collateral.symbol())
                            .add(loan.symbol())
                            .aggregate()
                            .await?;
                        let _ = tx.send(MarketParams {
                            id: market.id,
                            collateral_token: collateral,
                            loan_token: loan,
                            irm: market.marketParams.irm,
                            oracle: market.marketParams.oracle,
                            lltv: market.marketParams.lltv,
                        });
                    }
                }
            }

            Ok::<_, anyhow::Error>(())
        });
    }

    tokio::spawn(async move {
        // after 2 seconds, add 56 permits
        sleep(Duration::from_secs(2)).await;
        semaphore.add_permits(56);
    });

    drop(tx);

    let mut market_params = vec![];
    while let Some(create_market) = rx.recv().await {
        market_params.push(create_market);
    }

    bar.finish_and_clear();
    let bar = ProgressBar::new(market_params.len() as u64);

    let mut markets = vec![];
    let morpho = IMorpho::new(args.contract_address, provider);
    for params in &market_params {
        let data = morpho.market(params.id).call().await?;
        markets.push(data);
        bar.inc(1);
    }

    bar.finish_and_clear();

    let mut markets = market_params.into_iter().zip(markets).collect::<Vec<_>>();
    markets.sort_by_key(|(_, a)| a.totalBorrowAssets);

    for (params, market) in markets {
        println!("------------");
        println!("market: {}", params.id);
        println!("collateral: {}", params.collateral_token);
        println!("loan token: {}", params.loan_token);
        println!("oracle: {}", params.oracle);
        println!("irm: {}", params.irm);
        println!("LLTV: {}", params.lltv);
        println!("borrowed: {}", market.totalBorrowAssets);
        println!("supplied: {}", market.totalSupplyAssets);
    }

    Ok(())
}