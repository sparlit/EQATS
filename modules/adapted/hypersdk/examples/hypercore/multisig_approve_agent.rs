//! Approve an agent wallet through a multisig account on Hyperliquid.
//!
//! Demonstrates how multiple signers can collectively authorize an agent that acts on
//! behalf of a multisig wallet using the `multi_sig` API flow.

use std::{
    str::FromStr,
    time::{SystemTime, UNIX_EPOCH},
};

use clap::Parser;
use hypersdk::{
    Address,
    hypercore::{self as hypercore, Chain, PrivateKeySigner},
};

/// Example demonstrating how to approve an agent for a multisig account on Hyperliquid.
///
/// This example shows how to use Hyperliquid's L1 multisig functionality to approve
/// an agent that can act on behalf of a multisig account. This requires multiple signers
/// to authorize the agent approval, making it suitable for custody solutions, treasury
/// management, DAOs, or any scenario requiring multiple parties to approve account access.
///
/// # Multisig Flow
///
/// 1. Create the ApproveAgent action
/// 2. Each signer signs the action
/// 3. Collect all signatures into a MultiSigAction
/// 4. Submit the multisig transaction with all signatures
/// 5. The exchange verifies all signatures match the multisig wallet configuration
///
/// # Agent Limits
///
/// - 1 unnamed approved wallet per account
/// - Up to 3 named agents per account
/// - 2 named agents per subaccount
///
/// # Usage
///
/// ```bash
/// # Approve a named agent for multisig account
/// cargo run --example multisig_approve_agent -- \
///   --private-key KEY1 \
///   --private-key KEY2 \
///   --private-key KEY3 \
///   --multisig-address 0x... \
///   --agent 0x97271b6b7f3b23a2f4700ae671b05515ae5c3319 \
///   --name "trading_bot" \
///   --chain mainnet
///
/// # Approve an unnamed agent (leave out --name)
/// cargo run --example multisig_approve_agent -- \
///   --private-key KEY1 \
///   --private-key KEY2 \
///   --multisig-address 0x... \
///   --agent 0x... \
///   --chain mainnet
/// ```
///
/// # Security Notes
///
/// - All private keys must correspond to authorized signers on the multisig wallet
/// - The multisig wallet must have been configured on Hyperliquid beforehand
/// - Each transaction requires a unique nonce (timestamp is used for this)
/// - The approved agent will have full access to act on behalf of the account
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Cli {
    /// Private keys of the signers (must be authorized on the multisig wallet)
    #[arg(long)]
    private_key: Vec<String>,

    /// Multisig wallet address
    #[arg(long)]
    multisig_address: Address,

    /// Agent address to approve
    #[arg(long)]
    agent: Address,

    /// Agent name (optional, leave empty for unnamed agent)
    #[arg(long, default_value = "")]
    name: String,

    /// Chain to execute on (mainnet or testnet)
    #[arg(long, default_value_t = Chain::Testnet)]
    chain: Chain,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let args = Cli::parse();

    // Initialize logger for debugging
    let _ = simple_logger::init_with_level(log::Level::Debug);

    // Create HTTP client for the specified chain
    let client = hypercore::HttpClient::new(args.chain);

    // Parse all private keys into signers
    // Each signer must be authorized on the multisig wallet
    let signers: Vec<_> = args
        .private_key
        .iter()
        .map(|key| PrivateKeySigner::from_str(key.as_str()).unwrap())
        .collect();

    println!("Multisig wallet: {}", args.multisig_address);
    println!("Agent to approve: {}", args.agent);
    if !args.name.is_empty() {
        println!("Agent name: {}", args.name);
    } else {
        println!("Agent will be unnamed");
    }
    println!("Number of signers: {}", signers.len());

    // Generate timestamp for nonce
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;

    println!("\nInitiating multisig agent approval...");
    println!("Nonce: {}", now);

    // Execute multisig agent approval
    // 1. First signer is the lead (submits the transaction)
    // 2. All signers (including lead) sign the action
    // 3. Signatures are collected and verified
    // 4. Transaction is submitted to the exchange
    client
        .multi_sig(&signers[0], args.multisig_address, now)
        .signers(&signers)
        .approve_agent(args.agent, args.name.clone())
        .await?;

    println!("\n✅ Multisig agent approval successful!");
    if !args.name.is_empty() {
        println!(
            "Agent '{}' ({}) approved for multisig account {}",
            args.name, args.agent, args.multisig_address
        );
    } else {
        println!(
            "Unnamed agent ({}) approved for multisig account {}",
            args.agent, args.multisig_address
        );
    }

    Ok(())
}