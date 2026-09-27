use std::time::Duration;

use axum::{extract::DefaultBodyLimit, routing::post, Router};

use super::{handle_messages, handle_messages_claudecode};

const MAX_REQUEST_BODY_BYTES: usize = 64 * 1024 * 1024;

#[derive(Clone)]
pub struct AppState {
    pub(crate) http_client: reqwest::Client,
}

pub async fn run(listener: std::net::TcpListener) -> Result<(), String> {
    let http_client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(30))
        .tcp_keepalive(Duration::from_secs(60))
        .build()
        .map_err(|e| format!("reqwest client build failed: {e}"))?;

    let app = Router::new()
        .route("/v1/messages", post(handle_messages))
        .route("/claudecode/v1/messages", post(handle_messages_claudecode))
        .layer(DefaultBodyLimit::max(MAX_REQUEST_BODY_BYTES))
        .with_state(AppState { http_client });

    let listener = tokio::net::TcpListener::from_std(listener).map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();

    log::info!("[AnthropicProxy] listening on 127.0.0.1:{port}");
    axum::serve(listener, app)
        .await
        .map_err(|e| format!("serve failed: {e}"))
}