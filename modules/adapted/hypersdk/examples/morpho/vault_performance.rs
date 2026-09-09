//! Track MetaMorpho vault performance for a specific user.
//!
//! This example analyzes a user's deposit and withdrawal history in a MetaMorpho vault,
//! calculating their profit/loss and performance over time. It's useful for portfolio
//! tracking, performance analytics, and building vault monitoring dashboards.
//!
//! # Usage
//!
//! ```bash
//! # Track vault performance for a user
//! cargo run --example vault_performance -- \
//!   --user 0x1234567890abcdef1234567890abcdef12345678 \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//!
//! # Custom vault address
//! cargo run --example vault_performance -- \
//!   --contract-address 0x... \
//!   --user 0x... \
//!   --rpc-url https://rpc.hyperliquid.xyz/evm
//! ```
//!
//! # What it does
//!
//! 1. Connects to HyperEVM via RPC
//! 2. Scans blockchain for user's deposit/withdraw events in the vault
//! 3. Tracks share balances and asset values over time
//! 4. Calculates unrealized PnL at regular intervals
//! 5. Shows realized PnL on withdrawals
//!
//! # Output
//!
//! ```text
//! 5000000: 12.5
//! << Deposit (Block 5100000):
//!   Owner:  0x1234...
//!   Sender: 0x1234...
//!   Shares: 1000000000000000000
//!   Assets: 1000000000
//! 5200000: 15.3
//! >> Withdraw (Block 5300000), total pnl: 18.7:
//!   Owner:  0x1234...
//!   Sender: 0x1234...
//!   Shares: 500000000000000000
//!   Assets: 518700000
//! ```
//!
//! # Understanding Performance Tracking
//!
//! - **Block numbers**: Show when events occurred
//! - **PnL values**: Profit/loss in underlying asset (e.g., USDC)
//! - **Shares**: ERC-4626 vault share tokens
//! - **Assets**: Underlying asset amount (increases as vault earns yield)
//!
//! The example uses concurrent fetching with rate limiting to efficiently
//! scan the entire blockchain history.

use std::sync::Arc;

use alloy::{primitives::utils, rpc::types::Filter, sol_types::SolEvent};
use clap::Parser;
use futures::{FutureExt, StreamExt, stream::FuturesOrdered};
use hypersdk::hyperevm::{
    self, Address, DynProvider, ERC20,
    IERC4626::{self, Deposit, IERC4626Instance, Withdraw},
    ProviderTrait, U256,
};
use tokio::sync::Semaphore;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Cli {
    /// The address of the morpho vault.
    #[arg(
        short,
        long,
        default_value = "0xfc5126377f0efc0041c0969ef9ba903ce67d151e"
    )]
    contract_address: Address,

    #[arg(short, long)]
    user: Address,

    #[arg(short, long, default_value = "http://127.0.0.1:8545")]
    rpc_url: String,
}

struct Performance {
    // shares and their value
    // shares: VecDeque<(U256, U256)>,
    deposited_shares: U256,
    deposited_assets: U256,
    decimals: u8,
    accrued_value_in_asset: U256,
}

impl Performance {
    async fn accrued_value(
        &mut self,
        block: u64,
        vault: IERC4626Instance<DynProvider>,
    ) -> anyhow::Result<Option<String>> {
        if self.deposited_assets == 0 {
            return Ok(None);
        }

        let current_value = vault
            .convertToAssets(self.deposited_shares)
            .block(block.into())
            .call()
            .await?;
        // delta
        self.accrued_value_in_asset = current_value
            .checked_sub(self.deposited_assets)
            .unwrap_or_default();

        Ok(Some(utils::format_units(
            self.accrued_value_in_asset,
            self.decimals,
        )?))
    }

    fn deposit(&mut self, assets: U256, shares: U256) {
        self.deposited_assets += assets;
        self.deposited_shares += shares;
    }

    fn withdraw(&mut self, assets: U256, shares: U256) {
        // we can withdraw more than what we deposit, but not more shares
        self.deposited_assets = self.deposited_assets.saturating_sub(assets);
        self.deposited_shares -= shares;
    }
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _ = simple_logger::init_with_level(log::Level::Debug);
    let args = Cli::parse();

    println!("Connecting to RPC endpoint: {}", args.rpc_url);

    let provider = DynProvider::new(hyperevm::mainnet_with_url(&args.rpc_url).await?);
    let current_block = provider.get_block_number().await?;

    let vault = IERC4626::new(args.contract_address, provider.clone());
    let pool_asset_address = vault.asset().call().await?;

    let pool_asset = ERC20::new(pool_asset_address, provider.clone());
    let decimals = pool_asset.decimals().call().await?;

    enum Event {
        Report { block: u64 },
        Deposit { block: u64, deposit: Deposit },
        Withdraw { block: u64, withdraw: Withdraw },
    }

    // limit concurrency
    let semaphore = Arc::new(Semaphore::new(64));
    let mut futures = FuturesOrdered::new();
    for from_block in (0..=current_block).step_by(100_000) {
        let to_block = from_block + 100_000;

        for tenth in (from_block..=to_block).step_by(10_000) {
            let from_block = tenth;
            let to_block = tenth + 10_000;

            let filter = Filter::new()
                .address(args.contract_address)
                .event_signature(vec![
                    IERC4626::Deposit::SIGNATURE_HASH,
                    IERC4626::Withdraw::SIGNATURE_HASH,
                ])
                .from_block(from_block)
                .to_block(to_block)
                .topic1(args.user);

            let semaphore = Arc::clone(&semaphore);
            let provider = provider.clone();
            futures.push_back(
                async move {
                    let _permit = semaphore.acquire().await.unwrap();

                    // println!("Fetching from {from_block} to {to_block}");
                    let logs = provider.get_logs(&filter).await?;
                    if logs.is_empty() {
                        return Ok(vec![Event::Report {
                            block: (to_block + from_block) / 2,
                        }]);
                    }

                    let mut events = vec![];

                    for log in logs {
                        let Some(topic0) = log.topic0() else {
                            continue;
                        };

                        let block = log.block_number.unwrap();

                        match *topic0 {
                            IERC4626::Deposit::SIGNATURE_HASH => {
                                // Decode the log data using the type generated by the sol! macro
                                let deposit = IERC4626::Deposit::decode_log_data(&log.inner)
                                    .map_err(|e| {
                                        anyhow::anyhow!("Failed to decode log data: {}", e)
                                    })?;

                                events.push(Event::Deposit { block, deposit });
                            }
                            IERC4626::Withdraw::SIGNATURE_HASH => {
                                // Decode the log data using the type generated by the sol! macro
                                let withdraw = IERC4626::Withdraw::decode_log_data(&log.inner)
                                    .map_err(|e| {
                                        anyhow::anyhow!("Failed to decode log data: {}", e)
                                    })?;

                                events.push(Event::Withdraw { block, withdraw });
                            }
                            _ => unreachable!(),
                        }
                    }

                    Ok::<_, anyhow::Error>(events)
                }
                .boxed_local(),
            );
        }
    }

    // performance
    let mut performance = Performance {
        deposited_assets: U256::from(0),
        accrued_value_in_asset: U256::from(0),
        deposited_shares: U256::from(0),
        decimals,
    };

    while let Some(events) = futures.next().await {
        for event in events? {
            match event {
                Event::Report { block } => {
                    if let Some(pnl) = performance.accrued_value(block, vault.clone()).await? {
                        println!("{block}: {pnl}");
                    }
                }
                Event::Deposit { block, deposit } => {
                    println!("<< Deposit (Block {block}):");
                    println!("  Owner:  {}", deposit.owner);
                    println!("  Sender: {}", deposit.sender);
                    println!("  Shares: {}", deposit.shares);
                    println!("  Assets: {}", deposit.assets);
                    performance.deposit(deposit.assets, deposit.shares);
                    performance.accrued_value(block, vault.clone()).await?;
                }
                Event::Withdraw { block, withdraw } => {
                    if let Some(pnl) = performance.accrued_value(block, vault.clone()).await? {
                        println!(">> Withdraw (Block {block}), total pnl: {pnl}:");
                        println!("  Owner:  {}", withdraw.owner);
                        println!("  Sender: {}", withdraw.sender);
                        println!("  Shares: {}", withdraw.shares);
                        println!("  Assets: {}", withdraw.assets);
                    }
                    performance.withdraw(withdraw.assets, withdraw.shares);
                }
            }
        }
    }

    Ok(())
}