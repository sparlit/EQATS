//! Tauri command wrappers for the "我的AI生涯" (My AI Career) page.
//! Thin layer over [`crate::services::ai_career`]; the file I/O runs on the
//! blocking thread pool so it never stalls the IPC dispatcher.

use crate::services::ai_career::{self, Family, HeatmapEntry, SavedSession};

/// One page of a single family's session history, newest first. The frontend
/// requests one family at a time (the selected family card) and pages in more
/// on scroll via `offset`.
#[tauri::command]
pub async fn ai_career_family_history(
    family: String,
    offset: usize,
    limit: usize,
) -> Result<Vec<SavedSession>, String> {
    let fam = Family::from_id(&family).ok_or_else(|| format!("unknown family: {family}"))?;
    tauri::async_runtime::spawn_blocking(move || ai_career::family_history(fam, offset, limit))
        .await
        .map_err(|e| format!("history task join failed: {e}"))
}

/// Contribution-heatmap entries across all six families (drives the heatmap
/// grid and the five summary stats, which the frontend derives from these).
#[tauri::command]
pub async fn ai_career_heatmap() -> Result<Vec<HeatmapEntry>, String> {
    tauri::async_runtime::spawn_blocking(ai_career::message_heatmap)
        .await
        .map_err(|e| format!("heatmap task join failed: {e}"))
}

/// Total on-disk byte size across all session files — the frontend divides
/// this by a bytes-per-token ratio for the approximate ("≈") cumulative
/// token count.
#[tauri::command]
pub async fn ai_career_token_bytes() -> Result<u64, String> {
    tauri::async_runtime::spawn_blocking(ai_career::estimate_token_bytes)
        .await
        .map_err(|e| format!("token estimate task join failed: {e}"))
}
