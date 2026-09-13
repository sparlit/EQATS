//! Approve an agent wallet for a Hyperliquid account.
//!
//! This example demonstrates how to approve an external agent address that can act on
//! behalf of your account, with optional naming constraints (1 unnamed + up to 3 named per account).

use std::time::{SystemTime, UNIX_EPOCH};

use clap::Parser;
use hypersdk::{
    Address,
    hypercore::{Chain, HttpClient},
};

use crate::credentials::Credentials;

mod credentials;

#[derive(Parser, Debug, derive_more::Deref)]
#[command(author, version, about, long_about = None)]
struct Cli {
    #[deref]
    #[command(flatten)]
    common: Credentials,
    /// Agent address to approve.
    #[arg(short, long)]
    agent: Option<Address>,
    /// Agent name (optional, leave empty for unnamed agent).
    #[arg(short, long, default_value = "")]
    name: String,
    #[arg(long, default_value_t = Chain::Testnet)]
    chain: Chain,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let _ = simple_logger::init_with_level(log::Level::Debug);

    let args = Cli::parse();
    let signer = args.get()?;

    let client = HttpClient::new(args.chain);
    let agent = args.agent.unwrap_or_else(Address::random);

    println!("Approving agent {} for account {}", agent, signer.address());
    if !args.name.is_empty() {
        println!("Agent name: {}", args.name);
    } else {
        println!("Agent will be unnamed");
    }

    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;

    client
        .approve_agent(&signer, agent, args.name, nonce)
        .await?;

    println!("Agent approved successfully!");

    Ok(())
}