//! Local HTTP exchange fixtures. These tests never use a real account or endpoint.
use axum::{Json, Router, extract::State, routing::post};
use serde_json::{Value, json};
use std::sync::Arc;
use tokio::sync::Mutex;

pub(crate) fn position(size: &str, upnl: &str, margin: &str) -> Value {
    json!({"type":"oneWay", "position": {
        "coin":"BTC", "szi":size, "entryPx":"100", "leverage":{"type":"isolated","value":5},
        "liquidationPx":null, "marginUsed":margin, "positionValue":"1000",
        "returnOnEquity":"0", "unrealizedPnl":upnl, "maxLeverage":50,
        "cumFunding":{"allTime":"2","sinceOpen":"2","sinceChange":"2"}
    }})
}

pub(crate) fn account(positions: Vec<Value>, value: &str, time: u64) -> Value {
    let summary =
        json!({"accountValue":value,"totalMarginUsed":"0","totalNtlPos":"0","totalRawUsd":value});
    json!({"assetPositions":positions,"marginSummary":summary,"crossMarginSummary":summary,
        "withdrawable":value,"time":time})
}

#[derive(Clone)]
struct ExchangeState {
    account: Arc<Mutex<Value>>,
    orders: Arc<Mutex<Value>>,
    requests: Arc<Mutex<Vec<Value>>>,
}

pub(crate) struct MockExchange {
    pub url: String,
    pub account: Arc<Mutex<Value>>,
    pub orders: Arc<Mutex<Value>>,
    pub requests: Arc<Mutex<Vec<Value>>>,
    task: tokio::task::JoinHandle<()>,
}

impl MockExchange {
    pub async fn new(account: Value) -> Self {
        let state = ExchangeState {
            account: Arc::new(Mutex::new(account)),
            orders: Arc::new(Mutex::new(json!([]))),
            requests: Arc::new(Mutex::new(Vec::new())),
        };
        let app = Router::new()
            .route("/info", post(info))
            .route("/exchange", post(exchange))
            .with_state(state.clone());
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let task = tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });
        Self {
            url,
            account: state.account,
            orders: state.orders,
            requests: state.requests,
            task,
        }
    }
    pub async fn wallet(&self) -> Arc<crate::Wallet> {
        Arc::new(crate::Wallet::for_test(self.url.clone()).await)
    }
}

impl Drop for MockExchange {
    fn drop(&mut self) {
        self.task.abort();
    }
}

async fn info(State(state): State<ExchangeState>, Json(body): Json<Value>) -> Json<Value> {
    state.requests.lock().await.push(body.clone());
    Json(match body["type"].as_str().unwrap() {
        "clearinghouseState" => state.account.lock().await.clone(),
        "frontendOpenOrders" => state.orders.lock().await.clone(),
        "userAbstraction" => json!("disabled"),
        "allMids" => json!({"BTC":"110"}),
        "activeAssetData" => json!({"leverage":{"type":"isolated","value":5}}),
        other => panic!("unexpected info request {other}"),
    })
}

async fn exchange(State(state): State<ExchangeState>, Json(body): Json<Value>) -> Json<Value> {
    state.requests.lock().await.push(body);
    Json(
        json!({"status":"ok","response":{"type":"order","data":{"statuses":[{"resting":{"oid":42}}]}}}),
    )
}