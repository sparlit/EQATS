use std::net::SocketAddr;
use std::sync::atomic::Ordering;

use axum::serve::Listener;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

pub(super) struct ServerControl {
    shutdown: CancellationToken,
    stopped: oneshot::Receiver<()>,
}

impl ServerControl {
    pub(super) fn start(listener: TcpListener, app: axum::Router) -> Self {
        let shutdown = CancellationToken::new();
        let signal = shutdown.clone();
        let (released, stopped) = oneshot::channel();
        let listener = TrackedListener {
            listener: Some(listener),
            released: Some(released),
        };
        super::RUNNING.store(true, Ordering::Relaxed);
        tauri::async_runtime::spawn(async move {
            let result = axum::serve(listener, app)
                .with_graceful_shutdown(signal.clone().cancelled_owned())
                .await;
            // A previous server may finish draining after a new one has started.
            if !signal.is_cancelled() {
                super::RUNNING.store(false, Ordering::Relaxed);
            }
            if let Err(error) = result {
                log::error!("[SmartRouter] serve failed: {error}");
            }
        });
        Self { shutdown, stopped }
    }

    pub(super) async fn stop(self) {
        self.shutdown.cancel();
        // Wait only for the listening socket to close. In-flight responses
        // drain independently and do not block the switch or a subsequent start.
        let _ = self.stopped.await;
        super::RUNNING.store(false, Ordering::Relaxed);
    }
}

struct TrackedListener {
    listener: Option<TcpListener>,
    released: Option<oneshot::Sender<()>>,
}

impl Listener for TrackedListener {
    type Io = TcpStream;
    type Addr = SocketAddr;

    async fn accept(&mut self) -> (Self::Io, Self::Addr) {
        Listener::accept(self.listener.as_mut().expect("live listener")).await
    }

    fn local_addr(&self) -> std::io::Result<Self::Addr> {
        self.listener.as_ref().expect("live listener").local_addr()
    }
}

impl Drop for TrackedListener {
    fn drop(&mut self) {
        drop(self.listener.take());
        if let Some(released) = self.released.take() {
            let _ = released.send(());
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::time::Duration;
    use tokio::sync::Notify;

    #[tokio::test]
    async fn stopping_releases_port_while_existing_request_finishes() {
        let entered = Arc::new(Notify::new());
        let finish = Arc::new(Notify::new());
        let app = axum::Router::new().route(
            "/",
            axum::routing::get({
                let entered = entered.clone();
                let finish = finish.clone();
                move || async move {
                    entered.notify_one();
                    finish.notified().await;
                    "completed"
                }
            }),
        );
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let server = ServerControl::start(listener, app);
        let request = tokio::spawn(async move {
            reqwest::Client::new()
                .get(format!("http://{addr}/"))
                .send()
                .await
                .unwrap()
        });
        tokio::time::timeout(Duration::from_secs(5), entered.notified())
            .await
            .unwrap();
        tokio::time::timeout(Duration::from_secs(5), server.stop())
            .await
            .unwrap();
        assert!(tokio::net::TcpStream::connect(addr).await.is_err());
        assert!(!request.is_finished());
        finish.notify_one();
        let response = tokio::time::timeout(Duration::from_secs(5), request)
            .await
            .unwrap()
            .unwrap();
        assert_eq!(response.text().await.unwrap(), "completed");
        let listener = TcpListener::bind(addr).await.unwrap();
        let restarted = ServerControl::start(
            listener,
            axum::Router::new().route("/", axum::routing::get(|| async { "restarted" })),
        );
        assert_eq!(
            reqwest::get(format!("http://{addr}/"))
                .await
                .unwrap()
                .text()
                .await
                .unwrap(),
            "restarted"
        );
        restarted.stop().await;
    }
}