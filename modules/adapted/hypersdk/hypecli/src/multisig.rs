//! Multi-signature transaction commands for hypecli.
//!
//! Supports sending assets, USD transfers, and spot transfers through a multisig wallet
//! using P2P peer coordination via iroh.

use std::{
    io::{Write, stdout},
    time::Duration,
};

use alloy::signers::Signer;
use clap::{Args, Subcommand};
use futures::{SinkExt, StreamExt};
use hypersdk::{
    Address, Decimal,
    hypercore::{
        self, AssetTarget, HttpClient, NonceHandler, Signature,
        api::{
            self, Action, ConvertToMultiSigUser, MultiSigAction, MultiSigPayload, SignersConfig,
        },
    },
};
use indicatif::{ProgressBar, ProgressStyle};
use iroh::{endpoint::Connection, protocol::Router};
use iroh_tickets::endpoint::EndpointTicket;
use serde::{Deserialize, Serialize};
use tokio::{
    io::{AsyncReadExt, stdin},
    signal::ctrl_c,
    sync::mpsc::unbounded_channel,
};
use tokio_util::codec::{FramedRead, FramedWrite};

use crate::{
    SignerArgs,
    utils::{self, find_signers},
};

/// Multi-sig commands regardless of your location.
///
/// This commands setups up a peer-to-peer communication
/// to allow for decentralized multi-sig.
#[derive(Subcommand)]
pub enum MultiSigCmd {
    Sign(MultiSigSign),
    Update(UpdateMultiSigCmd),
    SendAsset(MultiSigSendAsset),
    ConvertToNormalUser(ToNormalUserCmd),
}

impl MultiSigCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        match self {
            MultiSigCmd::Sign(cmd) => cmd.run().await,
            MultiSigCmd::SendAsset(cmd) => cmd.run().await,
            MultiSigCmd::ConvertToNormalUser(cmd) => cmd.run().await,
            MultiSigCmd::Update(cmd) => cmd.run().await,
        }
    }
}

/// Command to initiate sending an asset via multi-sig.
///
/// This command creates a multi-sig transaction proposal to send assets from
/// a multi-sig wallet. It uses peer-to-peer gossip to coordinate signatures
/// from authorized signers.
#[derive(Args, derive_more::Deref)]
pub struct MultiSigSendAsset {
    #[deref]
    #[command(flatten)]
    pub common: SignerArgs,
    /// Multi-sig wallet address.
    #[arg(long)]
    pub multi_sig_addr: Address,
    /// Destination address.
    #[arg(long)]
    pub to: Address,
    /// Token to send (symbol name, e.g., "USDC", "HYPE").
    #[arg(long)]
    pub token: String,
    /// Amount to send.
    #[arg(long)]
    pub amount: Decimal,
    /// Source DEX. Can be "spot" or a dex name.
    #[arg(long)]
    pub source: Option<String>,
    /// Destination DEX. Can be "spot" or a dex name.
    #[arg(long)]
    pub dest: Option<String>,
    /// Sign and submit using only local signers, without starting P2P gossip.
    #[arg(long)]
    pub local: bool,
}

impl MultiSigSendAsset {
    pub async fn run(self) -> anyhow::Result<()> {
        crate::send::SendCmd::from(self).run().await
    }
}

/// Command to sign a multi-sig transaction proposal.
///
/// This command connects to a peer who initiated a multi-sig transaction
/// and signs the proposed action if approved. Uses peer-to-peer gossip
/// for decentralized coordination.
#[derive(Args, derive_more::Deref)]
pub struct MultiSigSign {
    #[deref]
    #[command(flatten)]
    pub common: SignerArgs,
    /// Endpoint ticket to connect to the transaction initiator.
    #[arg(long)]
    pub connect: EndpointTicket,
    /// Multi-sig wallet address.
    #[arg(long)]
    pub multi_sig_addr: Address,
}

impl MultiSigSign {
    pub async fn run(self) -> anyhow::Result<()> {
        sign(self).await
    }
}

/// Command to convert a multi-signature user back to a normal user.
///
/// This command uses peer-to-peer gossip to collect signatures from authorized
/// signers to convert a multisig account back to a regular single-signer account.
#[derive(Args, derive_more::Deref)]
pub struct ToNormalUserCmd {
    #[deref]
    #[command(flatten)]
    pub common: SignerArgs,
    /// Multi-sig wallet address.
    #[arg(long)]
    pub multi_sig_addr: Address,
    /// Sign and submit using only local signers, without starting P2P gossip.
    #[arg(long)]
    pub local: bool,
}

impl ToNormalUserCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        convert_to_normal_user(self).await
    }
}

/// Update the multi-sig user.
#[derive(Args, derive_more::Deref)]
pub struct UpdateMultiSigCmd {
    #[deref]
    #[command(flatten)]
    common: SignerArgs,

    /// Authorized signer addresses (comma-separated)
    #[arg(long, required = true)]
    authorized_user: Vec<Address>,

    /// Signature threshold (number of signatures required)
    #[arg(long)]
    threshold: usize,

    /// Multi-sig wallet address.
    #[arg(long)]
    multi_sig_addr: Address,

    /// Sign and submit using only local signers, without starting P2P gossip.
    #[arg(long)]
    local: bool,
}

impl UpdateMultiSigCmd {
    pub async fn run(self) -> anyhow::Result<()> {
        update(self).await
    }
}

/// Animation strings for the connecting spinner.
const CONNECTING_STRINGS: &[&str] = &[
    "Connecting",
    "COnnecting",
    "CoNnecting",
    "ConNecting",
    "ConnEcting",
    "ConneCting",
    "ConnecTing",
    "ConnectIng",
    "ConnectiNg",
    "ConnectinG",
];

impl From<MultiSigSendAsset> for crate::send::SendCmd {
    fn from(cmd: MultiSigSendAsset) -> Self {
        Self {
            signer: crate::action::ActionArgs {
                signer: cmd.common,
                multi_sig_addr: Some(cmd.multi_sig_addr),
                local: cmd.local,
            },
            token: cmd.token,
            amount: cmd.amount,
            destination: Some(cmd.to),
            from: cmd
                .source
                .as_deref()
                .unwrap_or("perp")
                .parse()
                .unwrap_or(AssetTarget::Perp),
            to: cmd
                .dest
                .as_deref()
                .unwrap_or("perp")
                .parse()
                .unwrap_or(AssetTarget::Perp),
            from_subaccount: None,
        }
    }
}

async fn update(cmd: UpdateMultiSigCmd) -> anyhow::Result<()> {
    let hl = HttpClient::new(cmd.chain);
    let multisig_config = hl.multi_sig_config(cmd.multi_sig_addr).await?;
    let signers = find_signers(&cmd.common, &multisig_config.authorized_users).await?;

    for s in &signers {
        println!("Using signer {}", s.address());
    }

    let nonce = NonceHandler::default().next();

    let signature_chain_id = hl.chain().arbitrum_id().to_owned();
    let action = Action::from(ConvertToMultiSigUser {
        signature_chain_id,
        hyperliquid_chain: hl.chain(),
        signers: SignersConfig {
            authorized_users: cmd.authorized_user,
            threshold: cmd.threshold,
        },
        nonce,
    });

    let response = execute_multisig_action(
        cmd.multi_sig_addr,
        hl,
        signers,
        action,
        nonce,
        &multisig_config,
        cmd.local,
        &cmd.common.trezor,
    )
    .await?;
    api::Response::Ok(response).into_default()?;
    println!("Success");
    Ok(())
}

async fn convert_to_normal_user(cmd: ToNormalUserCmd) -> anyhow::Result<()> {
    let hl = HttpClient::new(cmd.chain);
    let multisig_config = hl.multi_sig_config(cmd.multi_sig_addr).await?;
    let signers = find_signers(&cmd.common, &multisig_config.authorized_users).await?;

    for s in &signers {
        println!("Using signer {}", s.address());
    }
    println!(
        "Converting multisig account {} to normal user",
        cmd.multi_sig_addr
    );

    let nonce = NonceHandler::default().next();

    let action = Action::ConvertToMultiSigUser(ConvertToMultiSigUser {
        signature_chain_id: cmd.chain.arbitrum_id().to_owned(),
        hyperliquid_chain: cmd.chain,
        signers: hypersdk::hypercore::api::SignersConfig {
            authorized_users: vec![], // Empty to convert to normal user
            threshold: 0,
        },
        nonce,
    });

    let response = execute_multisig_action(
        cmd.multi_sig_addr,
        hl,
        signers,
        action,
        nonce,
        &multisig_config,
        cmd.local,
        &cmd.common.trezor,
    )
    .await?;
    api::Response::Ok(response).into_default()?;
    println!("Success");
    Ok(())
}

async fn sign(cmd: MultiSigSign) -> anyhow::Result<()> {
    let multisig_config = HttpClient::new(cmd.chain)
        .multi_sig_config(cmd.multi_sig_addr)
        .await?;
    let signers = find_signers(&cmd.common, &multisig_config.authorized_users).await?;
    let key = utils::make_key(&signers[0]);

    for s in &signers {
        println!("Signer found using {}", s.address());
    }

    let pb = ProgressBar::new_spinner();
    pb.enable_steady_tick(Duration::from_millis(100));
    pb.set_style(
        ProgressStyle::with_template("{spinner} {msg}")
            .unwrap()
            .tick_strings(CONNECTING_STRINGS),
    );

    let (endpoint, _ticket) = utils::start_gossip(key, true).await?;

    let addr = cmd.connect.endpoint_addr();
    let conn = endpoint.connect(addr.clone(), proto::ALPN).await?;

    pb.finish_and_clear();

    let (send, recv) = conn.open_bi().await?;

    let mut read = FramedRead::new(recv, proto::Codec::default());
    let mut write = FramedWrite::new(send, proto::Codec::default());

    let _ = write.send(proto::Message::Hello).await;

    match read.next().await {
        Some(Ok(proto::Message::Action(nonce, action))) => {
            validate_proposal(
                &action,
                cmd.multi_sig_addr,
                &multisig_config.authorized_users,
            )?;
            println!("{:#?}", action);
            print!("Accept (y/n)? ");
            let _ = stdout().flush();
            let mut input = [0u8; 1];
            let _ = stdin().read_exact(&mut input).await;
            if input[0] == b'y' {
                let mut signed_addresses: Vec<Address> = Vec::new();
                for signer in &signers {
                    let signature = action.sign(signer, nonce, cmd.chain).await?;
                    println!("Signed with {}", signer.address());
                    signed_addresses.push(signer.address());
                    write.send(proto::Message::Signature(signature)).await?;
                }
                loop {
                    println!(
                        "Swap hardware wallet and press Enter to scan, or any other key to finish."
                    );
                    let mut swap_input = [0u8; 1];
                    let _ = stdin().read_exact(&mut swap_input).await;
                    if swap_input[0] != b'\n' {
                        break;
                    }
                    let new_signers = utils::scan_hw_signers(
                        &cmd.common.trezor,
                        &multisig_config.authorized_users,
                        &signed_addresses,
                    )
                    .await?;
                    if new_signers.is_empty() {
                        println!("No new hardware wallets found.");
                        continue;
                    }
                    for signer in &new_signers {
                        let signature = action.sign(signer, nonce, cmd.chain).await?;
                        println!("Signed with {}", signer.address());
                        signed_addresses.push(signer.address());
                        write.send(proto::Message::Signature(signature)).await?;
                    }
                }
            } else {
                println!("Rejected");
            }
        }
        _ => {
            anyhow::bail!("peer did not send a multisig proposal");
        }
    }

    conn.closed().await;
    endpoint.close().await;

    Ok(())
}

/// Execute a multisig action by collecting signatures from authorized signers.
///
/// This is the core multisig execution logic used by all multisig commands.
pub(crate) async fn execute_multisig_action(
    multi_sig_addr: Address,
    hl: HttpClient,
    signers: Vec<Box<dyn Signer + Send + Sync>>,
    inner_action: Action,
    nonce: u64,
    multisig_config: &hypersdk::hypercore::MultiSigConfig,
    local: bool,
    trezor_args: &crate::trezor::TrezorArgs,
) -> anyhow::Result<api::OkResponse> {
    let lead_signer = signers
        .first()
        .ok_or_else(|| anyhow::anyhow!("no signers found"))?;

    let action = MultiSigPayload {
        multi_sig_user: multi_sig_addr.to_string().to_lowercase(),
        outer_signer: lead_signer.address().to_string().to_lowercase(),
        action: Box::new(inner_action),
    };
    validate_proposal(&action, multi_sig_addr, &multisig_config.authorized_users)?;

    let mut signatures = vec![];
    let mut signed_addresses: Vec<Address> = Vec::new();

    for signer in &signers {
        if multisig_config.authorized_users.contains(&signer.address())
            && !signed_addresses.contains(&signer.address())
        {
            println!(
                "Using local signer {} to sign message:\n{action:#?}",
                signer.address()
            );
            let signature = action.sign(signer, nonce, hl.chain()).await?;
            record_signature(
                &action,
                signature,
                nonce,
                hl.chain(),
                &multisig_config.authorized_users,
                &mut signatures,
                &mut signed_addresses,
            )?;
        }
    }

    if !local && signatures.len() < multisig_config.threshold {
        collect_remote_signatures(
            &action,
            &mut signatures,
            &mut signed_addresses,
            nonce,
            &hl,
            multi_sig_addr,
            multisig_config,
            lead_signer,
            trezor_args,
        )
        .await?;
    }
    if signatures.len() < multisig_config.threshold {
        anyhow::bail!(
            "not enough local signers: have {} but need {}",
            signatures.len(),
            multisig_config.threshold
        );
    }

    let multi_sig_action = MultiSigAction {
        signature_chain_id: hl.chain().arbitrum_id().to_owned(),
        signatures,
        payload: action,
    };

    let req = hypercore::signing::multisig_lead_msg(
        lead_signer,
        multi_sig_action,
        nonce,
        None,
        None,
        hl.chain(),
    )
    .await?;

    match hl.send(req).await? {
        api::Response::Ok(response) => Ok(response),
        api::Response::Err(err) => {
            anyhow::bail!("{err}");
        }
    }
}

async fn collect_remote_signatures(
    action: &MultiSigPayload,
    signatures: &mut Vec<Signature>,
    signed_addresses: &mut Vec<Address>,
    nonce: u64,
    hl: &HttpClient,
    multi_sig_addr: Address,
    multisig_config: &hypersdk::hypercore::MultiSigConfig,
    lead_signer: &(dyn Signer + Send + Sync),
    trezor_args: &crate::trezor::TrezorArgs,
) -> anyhow::Result<()> {
    let key = utils::make_key(lead_signer);

    let pb = ProgressBar::new_spinner();
    pb.enable_steady_tick(Duration::from_millis(100));
    pb.set_style(
        ProgressStyle::with_template("{spinner} {msg}")
            .unwrap()
            .tick_strings(CONNECTING_STRINGS),
    );

    let (endpoint, ticket) = utils::start_gossip(key, true).await?;

    pb.finish_and_clear();

    let pb = ProgressBar::new(multisig_config.threshold as u64);
    pb.set_style(ProgressStyle::with_template("{msg}\nAuthorized {pos}/{len}").unwrap());
    pb.set_position(signatures.len() as u64);

    while signatures.len() < multisig_config.threshold {
        println!(
            "Swap hardware wallet and press Enter to scan, or any other key to wait for P2P peers."
        );
        let mut input = [0u8; 1];
        let _ = tokio::io::stdin().read_exact(&mut input).await;
        if input[0] != b'\n' {
            break;
        }
        let new_signers = utils::scan_hw_signers(
            trezor_args,
            &multisig_config.authorized_users,
            signed_addresses,
        )
        .await?;
        if new_signers.is_empty() {
            println!("No new hardware wallets found.");
            continue;
        }
        for signer in &new_signers {
            println!("Found new signer {}", signer.address());
            let signature = action.sign(signer, nonce, hl.chain()).await?;
            if record_signature(
                action,
                signature,
                nonce,
                hl.chain(),
                &multisig_config.authorized_users,
                signatures,
                signed_addresses,
            )? {
                pb.inc(1);
            }
        }
    }

    let (tx, mut rx) = unbounded_channel();
    let router = Router::builder(endpoint)
        .accept(
            proto::ALPN,
            proto::Serve((nonce, action.clone(), tx.clone())),
        )
        .spawn();

    let mut msgs = String::new();

    use std::fmt::Write;

    while signatures.len() < multisig_config.threshold {
        pb.set_message(format!(
            "Authorized users: {:?}\n{msgs}\nhypecli multisig sign --multi-sig-addr {} --chain {} --connect {}",
            multisig_config.authorized_users, multi_sig_addr, hl.chain(), ticket
        ));

        tokio::select! {
            _ = ctrl_c() => {
                router.shutdown().await?;
                anyhow::bail!("multisig signing cancelled");
            }
            Some(signature) = rx.recv() => {
                writeln!(&mut msgs, "> Receive signature {signature}")?;
                match record_signature(action, signature, nonce, hl.chain(), &multisig_config.authorized_users,
                    signatures, signed_addresses) {
                    Ok(true) => pb.inc(1),
                    Ok(false) => writeln!(&mut msgs, "> Ignored duplicate signer")?,
                    Err(err) => {
                        let _ = writeln!(&mut msgs, ">X unable to verify signature: {err}");
                    }
                }
            }
        }
    }

    pb.finish_and_clear();
    router.shutdown().await?;

    Ok(())
}

fn validate_proposal(
    action: &MultiSigPayload,
    expected_account: Address,
    authorized_users: &[Address],
) -> anyhow::Result<()> {
    let account: Address = action.multi_sig_user.parse()?;
    anyhow::ensure!(
        account == expected_account,
        "proposal targets {account}, expected {expected_account}"
    );
    let lead: Address = action.outer_signer.parse()?;
    anyhow::ensure!(
        authorized_users.contains(&lead),
        "proposal leader {lead} is not an authorized signer"
    );
    Ok(())
}

/// Count each authorized address once, regardless of which transport delivered it.
fn record_signature(
    action: &MultiSigPayload,
    signature: Signature,
    nonce: u64,
    chain: hypercore::Chain,
    authorized_users: &[Address],
    signatures: &mut Vec<Signature>,
    signed_addresses: &mut Vec<Address>,
) -> anyhow::Result<bool> {
    let address = action.recover(&signature, nonce, chain)?;
    anyhow::ensure!(
        authorized_users.contains(&address),
        "signature from unauthorized user {address}"
    );
    if signed_addresses.contains(&address) {
        return Ok(false);
    }
    signatures.push(signature);
    signed_addresses.push(address);
    Ok(true)
}

mod proto {
    use super::*;
    use bytes::{Bytes, BytesMut};
    use futures::SinkExt;
    use iroh::protocol::ProtocolHandler;
    use tokio::sync::mpsc::UnboundedSender;
    use tokio_util::codec::{self, LengthDelimitedCodec};

    pub const ALPN: &[u8] = b"/hypersdk-multisig/0";

    /// Messages exchanged over the gossip network during multi-sig coordination.
    #[derive(Serialize, Deserialize)]
    pub enum Message {
        /// We need to write something when opening the connection
        ///
        /// https://docs.rs/iroh/latest/iroh/endpoint/struct.Connection.html#method.accept_bi
        Hello,
        /// A proposed action with its nonce that needs to be signed.
        Action(u64, MultiSigPayload),
        /// A signature from an authorized signer.
        Signature(Signature),
    }

    #[derive(Default)]
    pub struct Codec {
        inner: LengthDelimitedCodec,
    }

    impl codec::Decoder for Codec {
        type Item = Message;
        type Error = anyhow::Error;

        fn decode(&mut self, src: &mut BytesMut) -> Result<Option<Self::Item>, Self::Error> {
            let payload = match self.inner.decode(src)? {
                Some(data) => data,
                None => {
                    return Ok(None);
                }
            };

            let msg = rmp_serde::from_slice(&payload)?;
            Ok(Some(msg))
        }
    }

    impl codec::Encoder<Message> for Codec {
        type Error = anyhow::Error;

        fn encode(&mut self, item: Message, dst: &mut BytesMut) -> Result<(), Self::Error> {
            let msg = rmp_serde::to_vec(&item)?;
            self.inner.encode(Bytes::from(msg), dst)?;
            Ok(())
        }
    }

    #[derive(Debug, Clone)]
    pub struct Serve(pub (u64, MultiSigPayload, UnboundedSender<Signature>));

    impl ProtocolHandler for Serve {
        fn accept(
            &self,
            connection: Connection,
        ) -> impl Future<Output = Result<(), iroh::protocol::AcceptError>> + Send {
            let (nonce, action, tx) = self.clone().0;
            async move {
                let (send, recv) = connection.accept_bi().await?;

                let mut read = FramedRead::new(recv, proto::Codec::default());
                let mut write = FramedWrite::new(send, proto::Codec::default());

                let _ = write.send(Message::Action(nonce, action)).await;
                loop {
                    match read.next().await {
                        Some(Ok(Message::Signature(sig))) => {
                            let _ = tx.send(sig);
                        }
                        Some(Ok(Message::Hello)) => {}
                        None => break Ok(()),
                        _ => {
                            println!("received unexpected msg");
                        }
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use alloy::signers::local::PrivateKeySigner;
    use clap::Parser;
    use hypercore::Chain;

    use crate::{Cli, Command};

    fn payload(lead: Address) -> MultiSigPayload {
        MultiSigPayload {
            multi_sig_user: "0x1111111111111111111111111111111111111111".into(),
            outer_signer: lead.to_string().to_lowercase(),
            action: Box::new(Action::Noop),
        }
    }

    #[test]
    fn top_level_and_legacy_normal_user_commands_accept_the_same_options() {
        let address = "0x1111111111111111111111111111111111111111";
        let options = ["--multi-sig-addr", address, "--chain", "testnet", "--local"];

        let mut top_level = vec!["hypecli", "to-normal-user"];
        top_level.extend(options);
        let Command::ToNormalUser(top_level) =
            Cli::try_parse_from(top_level).unwrap().command.unwrap()
        else {
            panic!("expected top-level to-normal-user command");
        };

        let mut legacy = vec!["hypecli", "multisig", "convert-to-normal-user"];
        legacy.extend(options);
        let Command::Multisig(MultiSigCmd::ConvertToNormalUser(legacy)) =
            Cli::try_parse_from(legacy).unwrap().command.unwrap()
        else {
            panic!("expected legacy convert-to-normal-user command");
        };

        assert_eq!(top_level.multi_sig_addr, legacy.multi_sig_addr);
        assert_eq!(top_level.chain, legacy.chain);
        assert_eq!(top_level.local, legacy.local);
    }

    #[test]
    fn proposal_must_target_requested_wallet_and_authorized_leader() {
        let signer = PrivateKeySigner::random();
        let proposal = payload(signer.address());
        let account = proposal.multi_sig_user.parse().unwrap();
        validate_proposal(&proposal, account, &[signer.address()]).unwrap();
        assert!(validate_proposal(&proposal, Address::ZERO, &[signer.address()]).is_err());
        assert!(validate_proposal(&proposal, account, &[Address::ZERO]).is_err());
    }

    #[test]
    fn repeated_and_unauthorized_signatures_do_not_advance_threshold() {
        let first = PrivateKeySigner::random();
        let second = PrivateKeySigner::random();
        let outsider = PrivateKeySigner::random();
        let action = payload(first.address());
        let authorized = [first.address(), second.address()];
        let mut signatures = Vec::new();
        let mut addresses = Vec::new();
        let nonce = 1_700_000_000_000;
        let first_sig = action.sign_sync(&first, nonce, Chain::Mainnet).unwrap();
        assert!(
            record_signature(
                &action,
                first_sig.clone(),
                nonce,
                Chain::Mainnet,
                &authorized,
                &mut signatures,
                &mut addresses
            )
            .unwrap()
        );
        assert!(
            !record_signature(
                &action,
                first_sig.clone(),
                nonce,
                Chain::Mainnet,
                &authorized,
                &mut signatures,
                &mut addresses
            )
            .unwrap()
        );
        assert!(
            record_signature(
                &action,
                action.sign_sync(&outsider, nonce, Chain::Mainnet).unwrap(),
                nonce,
                Chain::Mainnet,
                &authorized,
                &mut signatures,
                &mut addresses
            )
            .is_err()
        );
        let mut malformed = first_sig;
        malformed.v = 2;
        assert!(
            record_signature(
                &action,
                malformed,
                nonce,
                Chain::Mainnet,
                &authorized,
                &mut signatures,
                &mut addresses
            )
            .is_err()
        );
        assert_eq!(signatures.len(), 1);
        assert_eq!(addresses, [first.address()]);
        assert!(
            record_signature(
                &action,
                action.sign_sync(&second, nonce, Chain::Mainnet).unwrap(),
                nonce,
                Chain::Mainnet,
                &authorized,
                &mut signatures,
                &mut addresses
            )
            .unwrap()
        );
        assert_eq!(signatures.len(), 2);
        assert_eq!(addresses, authorized);
    }
}