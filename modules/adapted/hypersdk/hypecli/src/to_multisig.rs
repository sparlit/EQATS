//! Convert a regular user account to a multi-sig account.

use clap::Parser;
use hypersdk::{
    Address,
    hypercore::{HttpClient, NonceHandler},
};

use crate::{SignerArgs, utils};

/// Convert a regular user to a multi-sig user.
///
/// This command converts a regular account to a multi-sig account by specifying
/// the authorized signers and the required signature threshold.
#[derive(Parser, derive_more::Deref)]
pub struct ToMultiSigCmd {
    #[deref]
    #[command(flatten)]
    common: SignerArgs,

    /// Authorized signer addresses (comma-separated)
    #[arg(long, required = true)]
    authorized_user: Vec<Address>,

    /// Signature threshold (number of signatures required)
    #[arg(long)]
    threshold: usize,
}

impl ToMultiSigCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        let signer = utils::find_signer(&self.common, None).await?;
        let client = HttpClient::new(self.chain);

        println!("Converting user {} to multi-sig...", signer.address());
        println!("Authorized users: {:?}", self.authorized_user);
        println!("Threshold: {}", self.threshold);

        let nonce = NonceHandler::default().next();

        client
            .convert_to_multisig(&signer, self.authorized_user, self.threshold, nonce)
            .await?;

        println!(
            "Successfully converted {} to multi-sig user",
            signer.address()
        );

        Ok(())
    }
}