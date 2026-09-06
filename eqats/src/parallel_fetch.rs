use tokio::sync::mpsc;
use tokio::time::{self, Duration};
use std::collections::HashMap;
use std::sync::{Arc, Mutex, atomic::{AtomicI64, Ordering}};

struct Candle {
    symbol: String,
    timestamp: i64,
    open: f64,
    high: f64,
    low: f64,
    close: f64,
    volume: f64,
}

#[derive(Clone)]
struct DataStore {
    inner: Arc<Mutex<HashMap<String, Vec<Candle>>>>,
}

impl DataStore {
    fn new() -> Self {
        DataStore {
            inner: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    async fn upsert_candle(&self, candle: Candle) {
        let mut store = self.inner.lock().unwrap();
        store.entry(candle.symbol.clone())
            .or_default()
            .retain(|c| c.timestamp != candle.timestamp);
        store.get_mut(&candle.symbol).unwrap().push(candle);
        store.get_mut(&candle.symbol).unwrap().sort_by_key(|c| c.timestamp);
    }

    async fn get_candles(&self, symbol: &str) -> Option<Vec<Candle>> {
        let store = self.inner.lock().unwrap();
        store.get(symbol).cloned()
    }
}

static NEXT_TS: AtomicI64 = AtomicI64::new(0);

async fn worker(
    id: usize,
    symbol: String,
    mut rx: tokio::sync::mpsc::Receiver<()>,
    store: DataStore,
) {
    let mut interval = time::interval(Duration::from_secs(1));
    loop {
        tokio::select! {
            _ = interval.tick() => {
                let candle = Candle {
                    symbol: symbol.clone(),
                    timestamp: NEXT_TS.fetch_add(1, Ordering::Relaxed),
                    open: 100.0,
                    high: 101.0,
                    low: 99.0,
                    close: 100.5,
                    volume: 1000.0,
                };
                store.upsert_candle(candle).await;
            }
            Some(_) = rx.recv() => {
                println!("Worker {} for symbol {} shutting down", id, symbol);
                break;
            }
        }
    }
}

pub struct ParallelFetcher {
    store: DataStore,
    handles: Vec<tokio::task::JoinHandle<()>>,
    txs: Vec<tokio::sync::mpsc::Sender<()>>,
}

impl ParallelFetcher {
    pub fn new(symbols: Vec<String>) -> Self {
        let store = DataStore::new();
        let mut handles = Vec::new();
        let mut txs = Vec::new();
        for (i, symbol) in symbols.into_iter().enumerate() {
            let store_clone = store.clone();
            let (tx, rx) = tokio::sync::mpsc::channel(1);
            let handle = tokio::spawn(worker(i, symbol, rx, store_clone));
            handles.push(handle);
            txs.push(tx);
        }
        ParallelFetcher { store, handles, txs }
    }

    pub async fn shutdown(self) {
        for tx in self.txs {
            let _ = tx.send(()).await;
        }
        for handle in self.handles {
            let _ = handle.await;
        }
    }

    pub fn store(&self) -> DataStore {
        self.store.clone()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::time;

    #[tokio::test]
    async fn test_parallel_fetcher() {
        let symbols = vec!["INFY".to_string(), "TCS".to_string()];
        let fetcher = ParallelFetcher::new(symbols);
        let store = fetcher.store();
        time::sleep(time::Duration::from_secs(3)).await;
        drop(fetcher);
        let candles_infy = store.get_candles("INFY").await.unwrap_or_default();
        let candles_tcs = store.get_candles("TCS").await.unwrap_or_default();
        assert!(!candles_infy.is_empty());
        assert!(!candles_tcs.is_empty());
    }
}
