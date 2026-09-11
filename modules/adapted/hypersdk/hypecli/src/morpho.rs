//! Morpho protocol query commands.
//!
//! This module provides commands for querying positions on the Morpho lending
//! protocol deployed on HyperEVM.

use std::io::{Write, stdout};

use clap::Args;
use hypersdk::{
    Address, Decimal, U256, dec,
    hyperevm::{self, morpho},
};
use rust_decimal::{MathematicalOps, prelude::FromPrimitive};

/// Command to query a user's position in a Morpho lending market.
///
/// Queries the Morpho protocol on HyperEVM to retrieve a user's position data,
/// including borrow shares, collateral, and supply shares for a specific market.
///
/// # Example
///
/// ```bash
/// hypecli morpho-position \
///   --user 0x1234567890abcdef1234567890abcdef12345678 \
///   --market 0xabcd...1234
/// ```
///
/// # Output
///
/// Displays a table with columns:
/// - `borrow shares`: Amount of borrow shares held
/// - `collateral`: Collateral amount deposited
/// - `supply shares`: Amount of supply shares held
///
/// # Optional Arguments
///
/// - `--contract`: Morpho contract address (default: mainnet address)
/// - `--rpc-url`: Custom RPC endpoint (default: Hyperliquid mainnet)
#[derive(Args)]
pub struct MorphoPositionCmd {
    /// Morpho's contract address.
    #[arg(
        short,
        long,
        default_value = "0x68e37dE8d93d3496ae143F2E900490f6280C57cD"
    )]
    pub contract: Address,
    /// RPC endpoint URL for HyperEVM.
    #[arg(short, long, default_value = "https://rpc.hyperliquid.xyz/evm")]
    pub rpc_url: String,
    /// Morpho market ID to query.
    #[arg(short, long)]
    pub market: morpho::MarketId,
    /// Target user address.
    #[arg(short, long)]
    pub user: Address,
}

impl MorphoPositionCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        let provider = hyperevm::mainnet_with_url(&self.rpc_url).await?;
        let client = hyperevm::morpho::Client::new(provider);
        let morpho = client.instance(self.contract);
        let position = morpho.position(self.market, self.user).call().await?;

        let mut writer = tabwriter::TabWriter::new(stdout());

        writeln!(&mut writer, "borrow shares\tcollateral\tsupply shares")?;
        writeln!(
            &mut writer,
            "{}\t{}\t{}",
            position.borrowShares, position.collateral, position.supplyShares
        )?;

        writer.flush()?;

        Ok(())
    }
}

/// Command to query APY (Annual Percentage Yield) for Morpho lending markets.
///
/// Queries the Morpho protocol on HyperEVM to retrieve APY data for a specific
/// market, including both borrow and supply rates.
///
/// # Example
///
/// ```bash
/// hypecli morpho-apy \
///   --contract 0x68e37dE8d93d3496ae143F2E900490f6280C57cD \
///   --market 0xabcd...1234
/// ```
///
/// # Output
///
/// Displays a table with columns:
/// - `borrow apy`: Annual percentage yield for borrowing (as %)
/// - `supply apy`: Annual percentage yield for supplying (as %)
///
/// # Optional Arguments
///
/// - `--contract`: Morpho contract address (default: mainnet address)
/// - `--rpc-url`: Custom RPC endpoint (default: Hyperliquid mainnet)
#[derive(Args)]
pub struct MorphoApyCmd {
    /// Morpho's contract address.
    #[arg(
        short,
        long,
        default_value = "0x68e37dE8d93d3496ae143F2E900490f6280C57cD"
    )]
    pub contract: Address,
    /// RPC endpoint URL for HyperEVM.
    #[arg(short, long, default_value = "https://rpc.hyperliquid.xyz/evm")]
    pub rpc_url: String,
    /// Morpho market ID to query.
    #[arg(short, long)]
    pub market: morpho::MarketId,
}

impl MorphoApyCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        let provider = hyperevm::mainnet_with_url(&self.rpc_url).await?;
        let client = hyperevm::morpho::Client::new(provider);
        let apy = client
            .apy::<Decimal, _>(self.contract, self.market, |e| e.exp())
            .await?;

        let mut writer = tabwriter::TabWriter::new(stdout());

        // Convert U256 to f64 for display (scaled by 1e18)
        let borrow_percent = apy.borrow * Decimal::ONE_HUNDRED;
        let supply_percent = apy.supply * Decimal::ONE_HUNDRED;

        writeln!(&mut writer, "borrow apy\tsupply apy")?;
        writeln!(
            &mut writer,
            "{:.4}%\t{:.4}%",
            borrow_percent, supply_percent
        )?;

        writer.flush()?;

        Ok(())
    }
}

/// Command to query APY for MetaMorpho vaults.
///
/// MetaMorpho vaults aggregate multiple Morpho markets to optimize yields.
/// This command displays the vault's effective APY after management fees.
///
/// # Example
///
/// ```bash
/// hypecli morpho-vault-apy \
///   --vault 0x1234567890abcdef1234567890abcdef12345678
/// ```
///
/// # Output
///
/// Displays vault APY information:
/// - `gross apy`: APY before fees
/// - `fee`: Management fee percentage
/// - `net apy`: Effective APY after fees
/// - `markets`: Number of markets in the vault
///
/// # Optional Arguments
///
/// - `--rpc-url`: Custom RPC endpoint (default: Hyperliquid mainnet)
#[derive(Args)]
pub struct MorphoVaultApyCmd {
    /// RPC endpoint URL for HyperEVM.
    #[arg(short, long, default_value = "https://rpc.hyperliquid.xyz/evm")]
    pub rpc_url: String,
    /// MetaMorpho vault address.
    #[arg(short, long)]
    pub vault: Address,
}

impl MorphoVaultApyCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        let provider = hyperevm::mainnet_with_url(&self.rpc_url).await?;
        let client = hyperevm::morpho::MetaClient::new(provider);
        let apy_data = client.apy::<Decimal, _>(self.vault, |e| e.exp()).await?;

        let mut writer = tabwriter::TabWriter::new(stdout());

        let convert = |n: U256| Decimal::from_u128(n.to::<u128>()).unwrap();

        // Calculate APY using U256 throughout, only convert to f64 for display
        let net_apy = apy_data.apy(convert);
        let fee_percent = convert(apy_data.fee) / dec!(1e18) * Decimal::ONE_HUNDRED;
        let net_apy_percent = net_apy * Decimal::ONE_HUNDRED;

        writeln!(&mut writer, "fee\tnet apy\tmarkets")?;
        writeln!(
            &mut writer,
            "{:.4}%\t{:.4}%\t{}",
            fee_percent,
            net_apy_percent,
            apy_data.market_count()
        )?;

        writer.flush()?;

        Ok(())
    }
}