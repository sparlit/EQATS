//! Monitor Uniswap V3 pool creation events on HyperEVM.
//!
//! This example scans the blockchain for Uniswap V3 PoolCreated events and displays
//! information about each newly created liquidity pool. It's useful for tracking new
//! trading pairs, market making opportunities, or DEX analytics.
//!
//! # Usage
//!
//! ```bash
//! # Using default settings (localhost RPC)
//! cargo run --example pools_created
//!
//! # Using Hyperliquid public RPC
//! cargo run --example pools_created -- \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//!
//! # Custom Uniswap factory address
//! cargo run --example pools_created -- \
//!   --contract-address 0x... \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//! ```
//!
//! # What it does
//!
//! 1. Connects to HyperEVM via RPC
//! 2. Scans blockchain in 100,000 block chunks (from current back to block 4M)
//! 3. Filters for Uniswap V3 PoolCreated events
//! 4. Resolves token symbols using ERC20 contract calls
//! 5. Displays pool details including address, fee tier, and token pair
//!
//! # Output
//!
//! ```text
//! Pool: 0x1234...
//! Address: 0x5678...
//! Fee: 3000
//! Token0: USDC
//! Token1: WETH
//! ----
//! ```
//!
//! # Fee Tiers
//!
//! - 100: 0.01% (for stablecoin pairs)
//! - 500: 0.05% (for low volatility pairs)
//! - 3000: 0.3% (standard fee tier)
//! - 10000: 1% (for exotic/high volatility pairs)

use alloy::{providers::Provider, rpc::types::Filter, sol_types::SolEvent};
use clap::Parser;
use hypersdk::hyperevm::{self, Address, uniswap::contracts::IUniswapV3Factory};

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Cli {
    /// Uniswap factory contract address.
    #[arg(
        short,
        long,
        default_value = "0xFf7B3e8C00e57ea31477c32A5B52a58Eea47b072"
    )]
    contract_address: Address,
    /// RPC url
    #[arg(short, long, default_value = "http://127.0.0.1:8545")]
    rpc_url: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _ = simple_logger::init_with_level(log::Level::Debug);
    let args = Cli::parse();

    let provider = hyperevm::mainnet_with_url(&args.rpc_url).await?;
    let current_block = provider.get_block_number().await?;

    let mut from_block = current_block;

    while from_block >= 4_000_000 {
        let to_block = from_block - 100_000;

        let filter = Filter::new()
            .address(args.contract_address)
            .event_signature(IUniswapV3Factory::PoolCreated::SIGNATURE_HASH)
            .from_block(to_block)
            .to_block(from_block);

        let logs = provider.get_logs(&filter).await?;
        for log in logs {
            let data = IUniswapV3Factory::PoolCreated::decode_log(&log.inner)?;
            let token0 = hyperevm::ERC20::new(data.token0, provider.clone());
            let token1 = hyperevm::ERC20::new(data.token1, provider.clone());

            let (token0, token1) = provider
                .multicall()
                .add(token0.symbol())
                .add(token1.symbol())
                .aggregate()
                .await?;

            println!("Pool: {}", data.pool);
            println!("Address: {}", data.address);
            println!("Fee: {}", data.fee);
            println!("Token0: {}", token0);
            println!("Token1: {}", token1);
            println!("----");
        }

        from_block = to_block;
    }

    Ok(())
}