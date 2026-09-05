use anyhow::{Context, Result};
use crossbeam_channel::Sender;
use futures::{SinkExt, StreamExt};
use serde_json::json;
use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use url::Url;
use tracing::{info, error, warn, debug};


#[derive(clap::Parser, Clone, Debug)]
#[command(author, version, about, long_about = None)]
pub struct IngestionArgs {
    #[arg(short, long, env = "SOL_WS", default_value = "wss://api.mainnet-beta.solana.com")]
    pub ws_url: String,

    #[arg(short, long, default_value = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")]
    pub program_id: String,
}

pub struct IngestionService {
    args: IngestionArgs,
    tx: Sender<String>,
}

impl IngestionService {
    pub fn new(args: IngestionArgs, tx: Sender<String>) -> Self {
        Self { args, tx }
    }

    pub async fn run(&self) -> Result<()> {
        info!("Connecting to WebSocket: {}", self.args.ws_url);
        let url = Url::parse(&self.args.ws_url).context("Invalid WebSocket URL")?;

        let (mut ws_stream, _) = connect_async(url).await.context("Failed to connect to WebSocket")?;
        info!("Connected to WebSocket");

        let subscribe_msg = json!({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "logsSubscribe",
            "params": [
                { "mentions": [self.args.program_id] },
                { "commitment": "processed" }
            ]
        }).to_string();

        ws_stream
            .send(Message::Text(subscribe_msg.into()))
            .await
            .context("Failed to send subscribe message")?;
        info!("Subscribed to logs for program: {}", self.args.program_id);

        while let Some(msg) = ws_stream.next().await {
            match msg {
                Ok(Message::Text(text)) => {
                    if let Err(e) = self.tx.try_send(text.to_string()) {
                        warn!("Parser channel full or closed: {:?}", e);
                    }
                }
                Ok(Message::Binary(bin)) => {
                    debug!("Received binary message of length: {}", bin.len());
                }
                Ok(Message::Ping(_)) => {}
                Ok(Message::Close(_)) => {
                    warn!("WebSocket closed by server");
                    break;
                }
                Ok(_) => {}
                Err(e) => {
                    error!("WebSocket error: {:?}", e);
                    break;
                }
            }
        }

        Ok(())
    }
}
