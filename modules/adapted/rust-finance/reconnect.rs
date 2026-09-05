use tokio_tungstenite::{connect_async, tungstenite::protocol::Message};
use tokio::time::{sleep, interval, Duration};
use url::Url;
use tracing::{info, warn};
use reqwest::Client;
use std::sync::Arc;
use tokio::sync::Mutex;
use serde_json::Value;
use crossbeam_channel::Sender as CbSender; 
use futures::{StreamExt, SinkExt};

/// Keeps last_slot processed; on reconnect, will fetch RPC blocks between last+1..current_slot
pub struct ResilientIngest {
    ws_urls: Vec<String>,
    selector: Arc<relay::NodeSelector>,
    last_slot: Arc<Mutex<Option<u64>>>,
    http: Client,
    out: CbSender<String>,
}

impl ResilientIngest {
    pub fn new(ws_urls: Vec<String>, selector: Arc<relay::NodeSelector>, out: CbSender<String>) -> Self {
        Self {
            ws_urls,
            selector,
            last_slot: Arc::new(Mutex::new(None)),
            http: Client::new(),
            out,
        }
    }

    /// MASTER LOOP
    pub async fn run(self: Arc<Self>) {
        let mut idx = 0usize;
        let mut backoff = 1;

        loop {
            let url_str = self.ws_urls[idx % self.ws_urls.len()].clone();
            info!("[WS] connecting to WS {}", url_str);

            match self.connect_and_stream(url_str.clone()).await {
                Ok(_) => {
                    backoff = 1; // reset after success
                }
                Err(e) => {
                    warn!("WS error {}: {:?}", url_str, e);
                    backoff = (backoff * 2).min(30);
                }
            }

            sleep(Duration::from_secs(backoff)).await;
            idx += 1;

            // replay any missed blocks
            if let Err(e) = self.replay_missed().await {
                warn!("Replay failed: {:?}", e);
            }
        }
    }

    /// CONNECT + STREAM LOOP
    async fn connect_and_stream(&self, ws_url: String) -> anyhow::Result<()> {
        let url = Url::parse(&ws_url)?;

        // TCP_NODELAY (big latency win) - connect_async does not easily expose socket options
        // unless we use a custom connector, but standard tokio-tungstenite is usually fine.
        // For true low-latency optimization we would use a custom connector here.
        let (ws_stream, _) = connect_async(url).await?;
        let (mut write, mut read) = ws_stream.split();

        // Subscribe immediately
        let subscribe = serde_json::json!({
            "jsonrpc":"2.0",
            "id":1,
            "method":"logsSubscribe",
            "params":[{"mentions":["TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"]}, {"commitment":"processed"}]
        }).to_string();
        write.send(Message::Text(subscribe.into())).await?;
        info!("[WS] subscribed to logs");

        // Ping keepalive (Solana drops idle connections)
        let mut ping_interval = interval(Duration::from_secs(15));

        loop {
            tokio::select! {
                _ = ping_interval.tick() => {
                    write.send(Message::Ping(Vec::new().into())).await?;
                }

                msg = read.next() => {
                    match msg {
                        Some(Ok(Message::Text(text))) => {
                            let _ = self.out.send(text.clone());

                            if let Ok(v) = serde_json::from_str::<Value>(&text) {
                                if let Some(slot) = extract_slot(&v) {
                                    let mut lock = self.last_slot.lock().await;
                                    *lock = Some(slot);
                                }
                            }
                        }

                        Some(Ok(Message::Ping(_))) => {
                            write.send(Message::Pong(Vec::new().into())).await?;
                        }

                        Some(Ok(Message::Close(_))) => {
                            warn!("WS closed by server");
                            break;
                        }

                        Some(Err(e)) => {
                            return Err(e.into());
                        }

                        None => break,
                        _ => {}
                    }
                }
            }
        }
        Ok(())
    }

    /// REPLAY MISSED BLOCKS (batch mode)
    async fn replay_missed(&self) -> anyhow::Result<()> {
        let last_slot = { *self.last_slot.lock().await };
        let rpc = self.selector.get_best().await;
        
        let head_slot = match get_slot_rpc(&self.http, &rpc).await {
            Ok(s) => s,
            Err(e) => {
                warn!("Failed to fetch head slot from {}: {:?}", rpc, e);
                return Err(e);
            }
        };

        if let Some(ls) = last_slot {
            if head_slot > ls {
                info!("[REPLAY] Replaying {} -> {}", ls, head_slot);

                let mut slot = ls + 1;
                while slot <= head_slot {
                    let end = (slot + 50).min(head_slot); // batch of 50 blocks
                    for s in slot..=end {
                        if let Ok(block) = get_block_rpc(&self.http, &rpc, s).await {
                            if let Some(txs) = block.get("transactions").and_then(|t| t.as_array()) {
                                for tx in txs {
                                    // Handle missing meta/logMessages gracefully
                                    if let Some(logs) = tx.get("meta").and_then(|m| m.get("logMessages")) {
                                        let payload = serde_json::json!({
                                            "replay_slot": s,
                                            "logs": logs
                                        }).to_string();
                                        let _ = self.out.send(payload);
                                    }
                                }
                            }
                        }
                    }
                    slot += 51;
                }

                let mut lock = self.last_slot.lock().await;
                *lock = Some(head_slot);
            }
        }
        Ok(())
    }
}

/// Extract slot from logsSubscribe message
fn extract_slot(v: &Value) -> Option<u64> {
    v.get("params")?
        .get("result")?
        .get("context")?
        .get("slot")?
        .as_u64()
}

async fn get_slot_rpc(client: &Client, rpc: &str) -> anyhow::Result<u64> {
    let body = serde_json::json!({
        "jsonrpc":"2.0","id":1,"method":"getSlot","params":[]
    });
    let resp = client.post(rpc).json(&body).send().await?.json::<Value>().await?;
    resp.get("result").and_then(|v| v.as_u64()).ok_or_else(|| anyhow::anyhow!("no slot result"))
}

async fn get_block_rpc(client: &Client, rpc: &str, slot: u64) -> anyhow::Result<Value> {
    let body = serde_json::json!({
        "jsonrpc":"2.0",
        "id":1,
        "method":"getBlock",
        "params":[slot,{
            "encoding":"json",
            "transactionDetails":"full",
            "maxSupportedTransactionVersion":0,
            "rewards": false
        }]
    });
    let resp = client.post(rpc).json(&body).send().await?.json::<Value>().await?;
    resp.get("result").cloned().ok_or_else(|| anyhow::anyhow!("no block result"))
}
