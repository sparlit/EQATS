// Parasite Commands — Tauri IPC for the Mother Agent's "Connect" mode.
// Currently delegates the turn to Claude Code only; the wrapped agent
// uses its own configured model (set via App Desktop or `claude /model`).

use crate::services::parasite::{self, SharedParasiteSessions};
use serde::Deserialize;
use tauri::{AppHandle, Emitter, State};

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ParasiteSendRequest {
    pub agent_id: String,
    pub message: String,
}

/// Return the IDs of parasitable agents that respond to `--version` locally.
/// Used by the frontend to decide which entries to show in the agent picker.
#[tauri::command]
pub async fn parasite_list_installed() -> Vec<String> {
    parasite::detect_installed().await
}

/// Run one turn against the selected agent. Streams a `parasite_event` event
/// stream back to the frontend (text_delta / error / done / state).
#[tauri::command]
pub async fn parasite_send_message(
    app: AppHandle,
    sessions: State<'_, SharedParasiteSessions>,
    request: ParasiteSendRequest,
) -> Result<(), String> {
    // Reject re-entry while the same agent is mid-turn so the user can't
    // stack overlapping subprocesses by mashing enter.
    {
        let map = sessions.lock().await;
        if let Some(sess) = map.get(&request.agent_id) {
            if sess.running {
                return Err(format!(
                    "Parasite agent '{}' is already processing a request",
                    request.agent_id
                ));
            }
        }
    }

    let sessions_clone = sessions.inner().clone();
    let app_clone = app.clone();
    let agent_id = request.agent_id.clone();
    let message = request.message;

    tokio::spawn(async move {
        if let Err(e) = parasite::send_message(app, sessions_clone, agent_id, message).await {
            log::error!("[ParasiteCommand] send_message error: {}", e);
            let _ = app_clone.emit(
                "parasite_event",
                serde_json::json!({"type": "error", "message": e}),
            );
            let _ = app_clone.emit("parasite_event", serde_json::json!({"type": "done"}));
        }
    });

    Ok(())
}

/// Cancel the in-flight turn for a specific agent (kills its subprocess).
/// Returns `true` when a running turn was actually interrupted.
#[tauri::command]
pub async fn parasite_abort(
    sessions: State<'_, SharedParasiteSessions>,
    agent_id: String,
) -> Result<bool, String> {
    let mut map = sessions.lock().await;
    if let Some(sess) = map.get_mut(&agent_id) {
        if sess.running {
            sess.abort();
            log::info!("[ParasiteCommand] aborted parasite agent: {}", agent_id);
            return Ok(true);
        }
    }
    Ok(false)
}

/// Forget the stored session ID for an agent so the next turn starts a fresh
/// conversation (Claude Code stops resuming the prior `--session-id`).
#[tauri::command]
pub async fn parasite_reset(
    sessions: State<'_, SharedParasiteSessions>,
    agent_id: String,
) -> Result<(), String> {
    let mut map = sessions.lock().await;
    if let Some(sess) = map.get_mut(&agent_id) {
        sess.session_id = None;
        log::info!("[ParasiteCommand] reset parasite session: {}", agent_id);
    }
    Ok(())
}
