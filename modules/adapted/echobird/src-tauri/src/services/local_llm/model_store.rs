// Model Store: fetch remote model list + download GGUF models + install llama-server engine

use futures_util::StreamExt;
use std::path::PathBuf;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::Emitter;

use super::gpu::get_gpu_info;
use super::server::LocalLlmServer;
use super::settings::get_download_dir;
use super::types::DownloadProgress;

// ─── Global download state ───

static DOWNLOAD_ABORT: AtomicBool = AtomicBool::new(false);
static DOWNLOAD_PAUSED: AtomicBool = AtomicBool::new(false);
// Holds all shard filenames of the currently-running download job. cancel_download
// reads this to know which .downloading temp files to wipe. Single-file engine
// installs wrap their identifier ("llama-server") in a one-element Vec to keep the
// shape uniform.
static DOWNLOAD_FILE: std::sync::Mutex<Option<Vec<String>>> = std::sync::Mutex::new(None);

// ─── Fetch store models ───

/// Fetch store models: remote → cache → empty fallback
pub async fn fetch_store_models() -> Vec<serde_json::Value> {
    let remote_url = "https://echobird.ai/api/store/models.json";
    let cache_dir = dirs::home_dir()
        .unwrap_or_default()
        .join(".echobird")
        .join("cache");
    let cache_path = cache_dir.join("store-models.json");

    // 1. Try remote
    if let Ok(resp) = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(8))
        .build()
        .unwrap_or_default()
        .get(remote_url)
        .header("User-Agent", "Echobird/1.1")
        .send()
        .await
    {
        if resp.status().is_success() {
            if let Ok(text) = resp.text().await {
                if let Ok(models) = serde_json::from_str::<Vec<serde_json::Value>>(&text) {
                    if !models.is_empty() {
                        let _ = std::fs::create_dir_all(&cache_dir);
                        let _ = std::fs::write(&cache_path, &text);
                        log::info!("[ModelStore] Loaded {} models from remote", models.len());
                        return models;
                    }
                }
            }
        }
    }

    // 2. Try cache
    if let Ok(text) = std::fs::read_to_string(&cache_path) {
        if let Ok(models) = serde_json::from_str::<Vec<serde_json::Value>>(&text) {
            if !models.is_empty() {
                log::info!("[ModelStore] Loaded {} models from cache", models.len());
                return models;
            }
        }
    }

    log::warn!("[ModelStore] No models available from remote or cache");
    vec![]
}

// ─── Model download (GGUF) ───

#[derive(Debug, Clone)]
struct DownloadSource {
    name: String,
    url: String,
}

fn build_download_sources(repo: &str, file_name: &str) -> Vec<DownloadSource> {
    vec![
        DownloadSource {
            name: "HuggingFace".to_string(),
            url: format!("https://huggingface.co/{}/resolve/main/{}", repo, file_name),
        },
        DownloadSource {
            name: "HF-Mirror".to_string(),
            url: format!("https://hf-mirror.com/{}/resolve/main/{}", repo, file_name),
        },
        DownloadSource {
            name: "ModelScope".to_string(),
            url: format!(
                "https://modelscope.cn/models/{}/resolve/master/{}",
                repo, file_name
            ),
        },
    ]
}

async fn test_source_speed(source: &DownloadSource) -> (String, f64) {
    let test_duration = std::time::Duration::from_secs(5);
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(15))
        .redirect(reqwest::redirect::Policy::limited(5))
        .build()
        .unwrap_or_default();

    let start = std::time::Instant::now();
    let mut bytes: u64 = 0;

    if let Ok(resp) = client
        .get(&source.url)
        .header("User-Agent", "Echobird/1.1")
        .send()
        .await
    {
        if resp.status().is_success() {
            let mut stream = resp.bytes_stream();
            while let Some(chunk) = stream.next().await {
                if start.elapsed() >= test_duration {
                    break;
                }
                if let Ok(data) = chunk {
                    bytes += data.len() as u64;
                }
            }
        }
    }

    let elapsed = start.elapsed().as_secs_f64();
    let speed = if elapsed > 0.0 {
        bytes as f64 / elapsed
    } else {
        0.0
    };
    log::info!(
        "[ModelStore] Speed test {}: {:.0} KB/s ({:.0} KB in {:.1}s)",
        source.name,
        speed / 1024.0,
        bytes as f64 / 1024.0,
        elapsed
    );
    (source.name.clone(), speed)
}

/// Emit a download-progress event. Centralised so adding fields (e.g.
/// shard_index/shard_count) is a one-line struct update rather than 17
/// scattered struct-literal edits.
fn emit_dl_progress(
    app: &tauri::AppHandle,
    file_name: &str,
    progress: u32,
    downloaded: u64,
    total: u64,
    status: &str,
    shard: Option<(u32, u32)>,
) {
    let _ = app.emit(
        "download-progress",
        DownloadProgress {
            file_name: file_name.to_string(),
            progress,
            downloaded,
            total,
            status: status.to_string(),
            shard_index: shard.map(|(i, _)| i),
            shard_count: shard.map(|(_, c)| c),
        },
    );
}

/// Download a model that may be a single GGUF or a sharded multi-file GGUF.
///
/// All shards share one speed-test round (we only re-run speed test for the
/// first shard); subsequent shards reuse the source ranking. Each shard gets
/// independent Range-resume + 3-source fallback. `file_name` reported in
/// progress events stays pinned to `files[0]` so the frontend's
/// Map<fileName, DownloadItem> keeps working across the whole job. Returns
/// the path of the first shard on success — callers (model scan) discover
/// the rest by listing the download directory.
pub async fn download_model(
    app_handle: tauri::AppHandle,
    repo: String,
    files: Vec<String>,
) -> Result<String, String> {
    if files.is_empty() {
        return Err("download_model: empty file list".to_string());
    }
    let download_dir = get_download_dir();
    let _ = std::fs::create_dir_all(&download_dir);

    // Primary key reported in progress events — pinned to the basename of
    // files[0] so the frontend (which scans the flat download dir and gets
    // basenames back) can match catalog -> in-progress download -> on-disk
    // file uniformly.
    let primary = std::path::Path::new(&files[0])
        .file_name()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| files[0].clone());
    let shard_count = files.len() as u32;
    let is_multi_shard = shard_count > 1;

    DOWNLOAD_ABORT.store(false, Ordering::SeqCst);
    DOWNLOAD_PAUSED.store(false, Ordering::SeqCst);
    *DOWNLOAD_FILE.lock().unwrap() = Some(files.clone());

    // Initial speed test against the first file. Subsequent shards reuse the
    // ranking — running a fresh 5s test per shard would cost minutes on a
    // 50-shard model with no signal value (HF/Mirror/ModelScope speed is
    // per-host-pair, not per-file).
    let sources = build_download_sources(&repo, &primary);

    emit_dl_progress(&app_handle, &primary, 0, 0, 0, "speed_test", None);

    log::info!(
        "[ModelStore] Speed testing {} sources for {} ({} shard{})...",
        sources.len(),
        primary,
        shard_count,
        if is_multi_shard { "s" } else { "" }
    );
    let speed_results = futures_util::future::join_all(sources.iter().map(test_source_speed)).await;

    let mut sorted: Vec<_> = speed_results
        .into_iter()
        .filter(|(_, speed)| *speed > 0.0)
        .collect();
    sorted.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    if sorted.is_empty() {
        // Speed test got no bytes in 5s. This isn't reliable on flaky
        // connections — HF's first-byte latency for sharded large files
        // can spike past 5s while the actual download streams fine.
        // Don't reject the job here; fall back to the default source
        // order and let try_download_shard's longer-lived connection
        // do the real attempt.
        log::warn!(
            "[ModelStore] Speed test got no signal in 5s for {} — falling back to default source order",
            primary
        );
        sorted = sources.iter().map(|s| (s.name.clone(), 0.0)).collect();
    } else {
        log::info!(
            "[ModelStore] Fastest source: {} ({:.0} KB/s)",
            sorted[0].0,
            sorted[0].1 / 1024.0
        );
    }

    // Track aggregated bytes across already-completed shards so the overall
    // progress bar climbs monotonically across shard boundaries.
    let mut aggregated_completed_bytes: u64 = 0;
    let mut first_shard_path: Option<String> = None;

    for (shard_idx_0, file_name) in files.iter().enumerate() {
        if DOWNLOAD_ABORT.load(Ordering::SeqCst) {
            *DOWNLOAD_FILE.lock().unwrap() = None;
            return Err("Download cancelled".to_string());
        }

        // `file_name` is the HF-side relative path, which for sharded unsloth
        // GGUFs includes a quantization subdir (e.g.
        // "UD-Q4_K_XL/Model-UD-Q4_K_XL-00001-of-00050.gguf"). The subdir is
        // needed to build the download URL, but we flatten on save so the
        // local tree matches what scan_gguf_files (which reports basenames)
        // expects — and so llama-server's --model arg points at a flat dir.
        let basename = std::path::Path::new(file_name)
            .file_name()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| file_name.clone());
        let save_path = PathBuf::from(&download_dir).join(&basename);
        let temp_path = save_path.with_file_name(format!("{}.downloading", &basename));

        // Skip shards already fully present on disk (e.g. resuming after
        // app restart, or partial completion before). isDownloaded check
        // on the frontend reflects whole-model state; per-shard we just
        // probe disk.
        if save_path.exists() {
            if let Ok(meta) = std::fs::metadata(&save_path) {
                aggregated_completed_bytes += meta.len();
            }
            log::info!(
                "[ModelStore] Shard {}/{} already on disk, skipping: {}",
                shard_idx_0 + 1,
                shard_count,
                file_name
            );
            if shard_idx_0 == 0 {
                first_shard_path = Some(save_path.to_string_lossy().to_string());
            }
            continue;
        }

        let shard_info = if is_multi_shard {
            Some((shard_idx_0 as u32 + 1, shard_count))
        } else {
            None
        };

        let shard_sources = build_download_sources(&repo, file_name);
        let mut shard_ok = false;
        for (source_name, _) in &sorted {
            let source = match shard_sources.iter().find(|s| &s.name == source_name) {
                Some(s) => s,
                None => continue,
            };
            match try_download_shard(
                &app_handle,
                source,
                &save_path,
                &temp_path,
                &primary,
                aggregated_completed_bytes,
                shard_info,
            )
            .await
            {
                Ok((path, shard_bytes)) => {
                    aggregated_completed_bytes += shard_bytes;
                    if shard_idx_0 == 0 {
                        first_shard_path = Some(path);
                    }
                    shard_ok = true;
                    break;
                }
                Err(e) => {
                    log::warn!(
                        "[ModelStore] {} failed on shard {}: {}",
                        source_name,
                        file_name,
                        e
                    );
                    if DOWNLOAD_ABORT.load(Ordering::SeqCst) {
                        *DOWNLOAD_FILE.lock().unwrap() = None;
                        return Err("Download cancelled".to_string());
                    }
                    if DOWNLOAD_PAUSED.load(Ordering::SeqCst) {
                        return Err("Download paused".to_string());
                    }
                }
            }
        }

        if !shard_ok {
            *DOWNLOAD_FILE.lock().unwrap() = None;
            emit_dl_progress(&app_handle, &primary, 0, 0, 0, "error", shard_info);
            return Err(format!(
                "All download sources failed for shard {}",
                file_name
            ));
        }
    }

    *DOWNLOAD_FILE.lock().unwrap() = None;
    emit_dl_progress(
        &app_handle,
        &primary,
        100,
        aggregated_completed_bytes,
        aggregated_completed_bytes,
        "completed",
        None,
    );
    log::info!(
        "[ModelStore] Download complete: {} ({} shard{}, {} bytes)",
        primary,
        shard_count,
        if is_multi_shard { "s" } else { "" },
        aggregated_completed_bytes
    );
    Ok(first_shard_path.unwrap_or_else(|| {
        PathBuf::from(&download_dir)
            .join(&primary)
            .to_string_lossy()
            .to_string()
    }))
}

/// Download one shard with Range-resume support. Returns the final on-disk
/// path and the total byte count for this shard so the caller can
/// accumulate overall progress across shards.
async fn try_download_shard(
    app_handle: &tauri::AppHandle,
    source: &DownloadSource,
    save_path: &PathBuf,
    temp_path: &PathBuf,
    primary_file_name: &str,
    aggregated_completed_bytes: u64,
    shard: Option<(u32, u32)>,
) -> Result<(String, u64), String> {
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::limited(10))
        .build()
        .map_err(|e| e.to_string())?;

    let start_byte: u64 = if temp_path.exists() {
        std::fs::metadata(temp_path).map(|m| m.len()).unwrap_or(0)
    } else {
        0
    };

    if start_byte > 0 {
        log::info!(
            "[ModelStore] [{}] Resume mode, {} bytes already downloaded",
            source.name,
            start_byte
        );
    }

    let mut request = client.get(&source.url).header("User-Agent", "Echobird/1.1");
    if start_byte > 0 {
        request = request.header("Range", format!("bytes={}-", start_byte));
    }

    let resp = request
        .send()
        .await
        .map_err(|e| format!("[{}] {}", source.name, e))?;
    let status = resp.status();
    if status != reqwest::StatusCode::OK && status != reqwest::StatusCode::PARTIAL_CONTENT {
        return Err(format!("[{}] HTTP {}", source.name, status.as_u16()));
    }

    let actual_start = if status == reqwest::StatusCode::OK && start_byte > 0 {
        0u64
    } else {
        start_byte
    };
    let content_length = resp.content_length().unwrap_or(0);
    let shard_total = actual_start + content_length;

    use std::io::Write;
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .append(actual_start > 0)
        .truncate(actual_start == 0)
        .open(temp_path)
        .map_err(|e| format!("File open error: {}", e))?;

    let mut downloaded_this_shard = actual_start;
    let mut stream = resp.bytes_stream();
    let mut last_emit = std::time::Instant::now();

    while let Some(chunk) = stream.next().await {
        if DOWNLOAD_ABORT.load(Ordering::SeqCst) {
            return Err("Download cancelled".to_string());
        }
        if DOWNLOAD_PAUSED.load(Ordering::SeqCst) {
            emit_dl_progress(
                app_handle,
                primary_file_name,
                0,
                aggregated_completed_bytes + downloaded_this_shard,
                aggregated_completed_bytes + shard_total,
                "paused",
                shard,
            );
            return Err("Download paused".to_string());
        }

        let data = chunk.map_err(|e| format!("[{}] Stream error: {}", source.name, e))?;
        file.write_all(&data)
            .map_err(|e| format!("Write error: {}", e))?;
        downloaded_this_shard += data.len() as u64;

        if last_emit.elapsed() >= std::time::Duration::from_millis(250) {
            // Progress is per-shard inside the bar — multi-shard UX shows
            // both the shard counter ("shard 3/10") in the subtitle and a
            // per-shard percentage. Aggregating into a single "total /
            // sum-of-totals" number sounds nicer but the sum-of-totals is
            // only known shard-by-shard, so the bar would jump as new
            // shard sizes become known. Per-shard % + shard counter is the
            // honest progress signal.
            let progress = if shard_total > 0 {
                ((downloaded_this_shard as f64 / shard_total as f64) * 100.0) as u32
            } else {
                0
            };
            emit_dl_progress(
                app_handle,
                primary_file_name,
                progress,
                aggregated_completed_bytes + downloaded_this_shard,
                aggregated_completed_bytes + shard_total,
                "downloading",
                shard,
            );
            last_emit = std::time::Instant::now();
        }
    }

    if save_path.exists() {
        let _ = std::fs::remove_file(save_path);
    }
    std::fs::rename(temp_path, save_path).map_err(|e| format!("Rename error: {}", e))?;

    log::info!(
        "[ModelStore] [{}] Shard complete: {}",
        source.name,
        save_path.display()
    );
    Ok((save_path.to_string_lossy().to_string(), shard_total))
}

/// Pause current download
pub fn pause_download() {
    DOWNLOAD_PAUSED.store(true, Ordering::SeqCst);
    log::info!("[ModelStore] Download paused");
}

/// Cancel download and delete temp files for ALL shards of the current job.
///
/// `target_files` lets a paused-then-cancelled UI explicitly name the shards
/// to wipe (because pause clears DOWNLOAD_FILE in the active loop). When
/// None, falls back to DOWNLOAD_FILE — the shards currently being downloaded.
pub fn cancel_download(app_handle: &tauri::AppHandle, target_files: Option<Vec<String>>) {
    DOWNLOAD_ABORT.store(true, Ordering::SeqCst);

    let files = target_files.or_else(|| DOWNLOAD_FILE.lock().unwrap().clone());

    if let Some(files) = &files {
        let download_dir = get_download_dir();
        for name in files {
            // Mirror download_model's flattening — temp files live next to
            // the final .gguf at the download dir root, keyed by basename.
            let basename = std::path::Path::new(name)
                .file_name()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| name.clone());
            let temp_path = PathBuf::from(&download_dir).join(format!("{}.downloading", &basename));
            if temp_path.exists() {
                let _ = std::fs::remove_file(&temp_path);
                log::info!("[ModelStore] Cleaned temp file: {}", temp_path.display());
            }
        }
        // UI tracks the job under files[0] as the primary key; emit the
        // basename to match what the download loop reports as fileName.
        if let Some(primary) = files.first() {
            let primary_basename = std::path::Path::new(primary)
                .file_name()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| primary.clone());
            emit_dl_progress(app_handle, &primary_basename, 0, 0, 0, "cancelled", None);
        }
    }

    *DOWNLOAD_FILE.lock().unwrap() = None;
    log::info!("[ModelStore] Download cancelled");
}

// ─── Engine version config (remote + cached + fallback) ───
//
// All three engines auto-track their upstream sources at runtime — no CDN
// snapshot or manual JSON bump required on our side:
//   • llama.cpp  ← api.github.com/repos/ggml-org/llama.cpp/releases/latest
//   • vllm       ← pypi.org/pypi/vllm/json
//   • sglang     ← pypi.org/pypi/sglang/json
// FALLBACK_LLAMA_VERSION is only used when GitHub is unreachable (offline,
// rate limit, etc.); the client falls back to the previously-cached map and
// finally to this constant. Bump it during release prep to a known-good build.

const FALLBACK_LLAMA_VERSION: &str = "b8999";
const FALLBACK_CUDA_VER: &str = "13.1";

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct EngineVersionInfo {
    pub version: String,
    #[serde(rename = "cudaVersion", default)]
    pub cuda_version: Option<String>,
    #[serde(default)]
    pub changelog: Option<String>,
}

/// Fetch engine versions: remote → cache → hardcoded fallback
pub fn get_engine_versions() -> std::collections::HashMap<String, EngineVersionInfo> {
    let cache_dir = dirs::home_dir()
        .unwrap_or_default()
        .join(".echobird")
        .join("cache");
    let cache_path = cache_dir.join("engine-versions.json");

    // Try cache first (synchronous — remote fetch is done in background)
    if let Ok(text) = std::fs::read_to_string(&cache_path) {
        if let Ok(map) = serde_json::from_str(&text) {
            return map;
        }
    }

    // Fallback defaults
    let mut map = std::collections::HashMap::new();
    map.insert(
        "llama-server".to_string(),
        EngineVersionInfo {
            version: FALLBACK_LLAMA_VERSION.to_string(),
            cuda_version: Some(FALLBACK_CUDA_VER.to_string()),
            changelog: None,
        },
    );
    map
}

/// Fetch latest version of a PyPI package
async fn fetch_pypi_latest(client: &reqwest::Client, package: &str) -> Option<String> {
    let url = format!("https://pypi.org/pypi/{}/json", package);
    let resp = client
        .get(&url)
        .header("User-Agent", "Echobird/3.0")
        .timeout(std::time::Duration::from_secs(6))
        .send()
        .await
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let json: serde_json::Value = resp.json().await.ok()?;
    json["info"]["version"].as_str().map(|s| s.to_string())
}

/// Fetch latest release tag of a GitHub repository. Unauthenticated; relies on
/// the 60 req/hour/IP allowance. On rate limit / network failure returns None
/// and the caller falls back to the cached or hardcoded version.
async fn fetch_github_latest_release_tag(client: &reqwest::Client, repo: &str) -> Option<String> {
    let url = format!("https://api.github.com/repos/{}/releases/latest", repo);
    let resp = client
        .get(&url)
        .header("User-Agent", "Echobird/3.0")
        .header("Accept", "application/vnd.github+json")
        .timeout(std::time::Duration::from_secs(6))
        .send()
        .await
        .ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let json: serde_json::Value = resp.json().await.ok()?;
    json["tag_name"].as_str().map(|s| s.to_string())
}

/// One pickable Windows CUDA build of llama.cpp — surfaced to the user
/// so they can choose which engine variant to install. Picker is gated
/// on Windows + NVIDIA in the frontend; non-NVIDIA variants are noise.
///
/// `rename_all = "camelCase"` so the JS side sees `cudaVersion` rather
/// than `cuda_version`.
#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LlamaReleaseOption {
    pub tag: String,
    pub cuda_version: String,
    pub asset_name: String,
    pub size_bytes: u64,
}

/// Fetch top N recent llama.cpp releases, emit one entry per Windows CUDA
/// variant per release. Newest first, flattened.
///
/// Returns empty Vec on network failure / rate-limit; the frontend should
/// fall back to the existing "auto-latest" install path.
pub async fn fetch_llama_release_options(top_n: usize) -> Vec<LlamaReleaseOption> {
    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(8))
        .build()
    {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let url = format!(
        "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page={}",
        top_n.clamp(1, 30)
    );
    let resp = match client
        .get(&url)
        .header("User-Agent", "Echobird/3.0")
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
    {
        Ok(r) if r.status().is_success() => r,
        _ => return Vec::new(),
    };

    let releases: Vec<serde_json::Value> = match resp.json().await {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };

    // Parse asset name "llama-<tag>-bin-win-cuda-<x.y>-x64.zip" without regex.
    // Returns Some((tag, cuda_version)) on match, None otherwise.
    fn parse_win_cuda_asset(name: &str) -> Option<(String, String)> {
        let stem = name
            .strip_prefix("llama-")
            .and_then(|s| s.strip_suffix("-x64.zip"))?;
        let marker = "-bin-win-cuda-";
        let idx = stem.find(marker)?;
        let tag = &stem[..idx];
        let cuda = &stem[idx + marker.len()..];
        // Sanity check cuda is "x.y" (digits, one dot)
        let mut parts = cuda.split('.');
        let (Some(a), Some(b), None) = (parts.next(), parts.next(), parts.next()) else {
            return None;
        };
        if !a.chars().all(|c| c.is_ascii_digit()) || !b.chars().all(|c| c.is_ascii_digit()) {
            return None;
        }
        Some((tag.to_string(), cuda.to_string()))
    }

    let mut out = Vec::new();
    for release in releases {
        let tag_in_release = release["tag_name"].as_str().map(|s| s.to_string());
        let assets = match release["assets"].as_array() {
            Some(a) => a,
            None => continue,
        };
        for asset in assets {
            let name = match asset["name"].as_str() {
                Some(s) => s,
                None => continue,
            };
            let (parsed_tag, cuda_version) = match parse_win_cuda_asset(name) {
                Some(t) => t,
                None => continue,
            };
            // Prefer the asset-name-embedded tag; the release tag is a fallback.
            let tag = if !parsed_tag.is_empty() {
                parsed_tag
            } else if let Some(t) = tag_in_release.clone() {
                t
            } else {
                continue;
            };
            let size_bytes = asset["size"].as_u64().unwrap_or(0);
            out.push(LlamaReleaseOption {
                tag,
                cuda_version,
                asset_name: name.to_string(),
                size_bytes,
            });
        }
    }

    out
}

/// Fetch engine versions from remote and cache locally (async, called on page load)
pub async fn refresh_engine_versions() -> std::collections::HashMap<String, EngineVersionInfo> {
    let cache_dir = dirs::home_dir()
        .unwrap_or_default()
        .join(".echobird")
        .join("cache");
    let cache_path = cache_dir.join("engine-versions.json");

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(6))
        .build()
        .unwrap_or_default();

    // All three engines fetched concurrently from their canonical upstreams.
    let (llama_tag, vllm_ver, sglang_ver) = tokio::join!(
        fetch_github_latest_release_tag(&client, "ggml-org/llama.cpp"),
        fetch_pypi_latest(&client, "vllm"),
        fetch_pypi_latest(&client, "sglang")
    );

    // Start with fallback / cached map
    let mut map = get_engine_versions();

    // Merge llama-server result
    if let Some(tag) = llama_tag {
        log::info!("[EngineVersions] llama.cpp latest from GitHub: {}", tag);
        map.insert(
            "llama-server".to_string(),
            EngineVersionInfo {
                version: tag,
                cuda_version: Some(FALLBACK_CUDA_VER.to_string()),
                changelog: None,
            },
        );
    }

    // Merge vllm latest
    if let Some(ver) = vllm_ver {
        log::info!("[EngineVersions] vllm latest from PyPI: {}", ver);
        map.insert(
            "vllm".to_string(),
            EngineVersionInfo {
                version: ver,
                cuda_version: None,
                changelog: None,
            },
        );
    }

    // Merge sglang latest
    if let Some(ver) = sglang_ver {
        log::info!("[EngineVersions] sglang latest from PyPI: {}", ver);
        map.insert(
            "sglang".to_string(),
            EngineVersionInfo {
                version: ver,
                cuda_version: None,
                changelog: None,
            },
        );
    }

    // Write merged result to cache
    if !map.is_empty() {
        if let Ok(json_str) = serde_json::to_string_pretty(&map) {
            let _ = std::fs::create_dir_all(&cache_dir);
            let _ = std::fs::write(&cache_path, &json_str);
        }
    }

    log::info!("[EngineVersions] Final map has {} engines", map.len());
    map
}

/// Persist the (version, cuda) that was actually installed to the
/// engine-versions.json cache. Called by install_local_engine after a
/// successful pick-driven install so detect-cuda's read-from-cache
/// path sees the canonical CUDA version.
fn persist_engine_version(engine_id: &str, version: &str, cuda_version: Option<&str>) {
    let cache_dir = dirs::home_dir()
        .unwrap_or_default()
        .join(".echobird")
        .join("cache");
    let cache_path = cache_dir.join("engine-versions.json");

    // Read current map (cache → fallback). Mutate the targeted entry, write back.
    let mut map = get_engine_versions();
    map.insert(
        engine_id.to_string(),
        EngineVersionInfo {
            version: version.to_string(),
            cuda_version: cuda_version.map(|s| s.to_string()),
            changelog: None,
        },
    );
    if let Ok(json_str) = serde_json::to_string_pretty(&map) {
        let _ = std::fs::create_dir_all(&cache_dir);
        let _ = std::fs::write(&cache_path, &json_str);
        log::info!(
            "[EngineVersions] Persisted user-picked install: {}={} (cuda={:?})",
            engine_id,
            version,
            cuda_version
        );
    }
}

// ─── Engine download: llama-server binary installer ───

fn llama_github_base(version: &str) -> String {
    format!(
        "https://github.com/ggml-org/llama.cpp/releases/download/{}",
        version
    )
}

fn llama_download_mirrors(version: &str) -> Vec<String> {
    let base = llama_github_base(version);
    vec![
        base.clone(),
        format!("https://ghfast.top/{}", base),
        format!("https://ghproxy.net/{}", base),
        format!("https://ghproxy.homeboyc.cn/{}", base),
        format!("https://github.ur1.fun/{}", base),
        format!("https://gh-proxy.com/{}", base),
        format!("https://mirror.ghproxy.com/{}", base),
    ]
}

fn classify_gpu_vendor_for_download(name: &str) -> &'static str {
    let n = name.to_lowercase();
    if n.contains("rtx")
        || n.contains("gtx")
        || n.contains("tesla")
        || n.contains("quadro")
        || n.contains("titan")
        || n.contains("nvidia")
        || n.starts_with("a100")
        || n.starts_with("h100")
        || n.starts_with("v100")
    {
        "nvidia"
    } else if n.contains("radeon")
        || n.contains("vega")
        || n.contains("rdna")
        || n.contains("amd")
        || n.starts_with("rx ")
    {
        "amd"
    } else {
        "other"
    }
}

fn get_llama_platform_files(
    has_nvidia: bool,
    has_amd: bool,
    version: &str,
    cuda_ver: &str,
) -> Vec<String> {
    match std::env::consts::OS {
        "windows" => {
            if has_nvidia {
                vec![
                    format!("llama-{}-bin-win-cuda-{}-x64.zip", version, cuda_ver),
                    format!("cudart-llama-bin-win-cuda-{}-x64.zip", cuda_ver),
                ]
            } else {
                // Upstream renamed the non-CUDA Windows build from `avx2` to
                // `cpu` somewhere before b8672. The old name 404s on every
                // recent release.
                vec![format!("llama-{}-bin-win-cpu-x64.zip", version)]
            }
        }
        "macos" => vec![format!("llama-{}-bin-macos-arm64.tar.gz", version)],
        _ => {
            let arch = std::env::consts::ARCH;
            if arch == "aarch64" || arch == "arm" {
                vec![format!("llama-{}-bin-ubuntu-arm64.tar.gz", version)]
            } else if has_nvidia || has_amd {
                // Upstream ships no Linux CUDA prebuilt; Vulkan covers
                // NVIDIA + AMD with a single binary, ~70-80% of native
                // CUDA perf, no compile step for the user.
                vec![format!("llama-{}-bin-ubuntu-vulkan-x64.tar.gz", version)]
            } else {
                vec![format!("llama-{}-bin-ubuntu-x64.tar.gz", version)]
            }
        }
    }
}

fn llama_install_dir() -> PathBuf {
    crate::utils::platform::echobird_dir().join("llama-server")
}

async fn test_mirror_speed(url: String, name: String) -> (String, String, f64) {
    let client = match reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::limited(10))
        .timeout(std::time::Duration::from_secs(10))
        .build()
    {
        Ok(c) => c,
        Err(_) => return (name, url, 0.0),
    };

    let start = std::time::Instant::now();
    let mut bytes: u64 = 0;

    if let Ok(resp) = client
        .get(&url)
        .header("User-Agent", "Echobird/1.1")
        .send()
        .await
    {
        if resp.status().is_success() {
            let mut stream = resp.bytes_stream();
            while let Some(chunk) = stream.next().await {
                if let Ok(data) = chunk {
                    bytes += data.len() as u64;
                }
                if start.elapsed() >= std::time::Duration::from_secs(5) {
                    break;
                }
            }
        }
    }

    let elapsed = start.elapsed().as_secs_f64();
    let speed = if elapsed > 0.0 {
        bytes as f64 / elapsed
    } else {
        0.0
    };
    log::info!(
        "[LlamaDownloader] Speed test {}: {:.0} KB/s ({} KB in {:.1}s)",
        name,
        speed / 1024.0,
        bytes / 1024,
        elapsed
    );
    (name, url, speed)
}

/// Download and install llama-server binary.
///
/// Optional overrides let the frontend's engine-version picker pin a
/// specific (tag, cuda) pair instead of auto-resolving "latest". If
/// both are `None`, the original auto-latest behavior runs unchanged.
pub async fn download_llama_server(
    app_handle: tauri::AppHandle,
    override_version: Option<String>,
    override_cuda: Option<String>,
) -> Result<String, String> {
    // Fetch latest version from remote config (used when overrides are absent)
    let versions = refresh_engine_versions().await;
    let llama_info = versions.get("llama-server");
    let version: String = override_version.unwrap_or_else(|| {
        llama_info
            .map(|i| i.version.clone())
            .unwrap_or_else(|| FALLBACK_LLAMA_VERSION.to_string())
    });
    let cuda_ver: String = override_cuda.unwrap_or_else(|| {
        llama_info
            .and_then(|i| i.cuda_version.clone())
            .unwrap_or_else(|| FALLBACK_CUDA_VER.to_string())
    });
    let version = version.as_str();
    let cuda_ver = cuda_ver.as_str();
    log::info!(
        "[LlamaDownloader] Using version={}, cuda={}",
        version,
        cuda_ver
    );

    let gpu_info = get_gpu_info();
    let gpu_vendor = gpu_info
        .as_ref()
        .map(|g| classify_gpu_vendor_for_download(&g.gpu_name))
        .unwrap_or("none");
    let has_nvidia = gpu_vendor == "nvidia";
    let has_amd = gpu_vendor == "amd";
    log::info!(
        "[LlamaDownloader] GPU vendor: {}, has_nvidia={}, has_amd={}",
        gpu_info
            .as_ref()
            .map(|g| g.gpu_name.as_str())
            .unwrap_or("none"),
        has_nvidia,
        has_amd
    );

    let file_names = get_llama_platform_files(has_nvidia, has_amd, version, cuda_ver);
    // Atomic install: extract to bin.new/, swap to bin/ only on success.
    // Cancelling or failing the download leaves the existing bin/ runnable.
    let bin_final = llama_install_dir().join("bin");
    let bin_dir = llama_install_dir().join("bin.new");
    let temp_dir = llama_install_dir().join("temp");
    let mirrors = llama_download_mirrors(version);

    DOWNLOAD_ABORT.store(false, Ordering::SeqCst);
    DOWNLOAD_PAUSED.store(false, Ordering::SeqCst);
    *DOWNLOAD_FILE.lock().unwrap() = Some(vec!["llama-server".to_string()]);

    // Clear any leftover bin.new from a previous interrupted run.
    let _ = std::fs::remove_dir_all(&bin_dir);
    let _ = std::fs::create_dir_all(&bin_dir);
    let _ = std::fs::create_dir_all(&temp_dir);

    let total_files = file_names.len();

    for (completed_files, file_name) in file_names.iter().enumerate() {
        if DOWNLOAD_ABORT.load(Ordering::SeqCst) {
            let _ = std::fs::remove_dir_all(&temp_dir);
            let _ = std::fs::remove_dir_all(&bin_dir);
            *DOWNLOAD_FILE.lock().unwrap() = None;
            return Err("Download cancelled".to_string());
        }

        let temp_file = temp_dir.join(file_name);

        emit_dl_progress(&app_handle, "llama-server", 0, 0, 0, "speed_test", None);

        log::info!(
            "[LlamaDownloader] Speed testing {} mirrors for {}...",
            mirrors.len(),
            file_name
        );
        let speed_results =
            futures_util::future::join_all(mirrors.iter().enumerate().map(|(i, mirror)| {
                let url = format!("{}/{}", mirror, file_name);
                let name = if i == 0 {
                    "GitHub".to_string()
                } else {
                    url::Url::parse(mirror)
                        .map(|u| u.host_str().unwrap_or("unknown").to_string())
                        .unwrap_or_else(|_| format!("Mirror-{}", i))
                };
                test_mirror_speed(url, name)
            }))
            .await;

        let mut sorted: Vec<_> = speed_results
            .into_iter()
            .filter(|(_, _, speed)| *speed > 0.0)
            .collect();
        sorted.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal));

        if sorted.is_empty() {
            emit_dl_progress(&app_handle, "llama-server", 0, 0, 0, "error", None);
            *DOWNLOAD_FILE.lock().unwrap() = None;
            return Err("All download mirrors unreachable".to_string());
        }

        log::info!(
            "[LlamaDownloader] Fastest: {} ({:.0} KB/s)",
            sorted[0].0,
            sorted[0].2 / 1024.0
        );

        let mut download_ok = false;
        for (mirror_name, mirror_url, _) in &sorted {
            if DOWNLOAD_ABORT.load(Ordering::SeqCst) {
                break;
            }
            log::info!(
                "[LlamaDownloader] Downloading via {}: {}",
                mirror_name,
                mirror_url
            );
            match download_engine_file(
                &app_handle,
                mirror_url,
                &temp_file,
                completed_files as u32,
                total_files as u32,
            )
            .await
            {
                Ok(_) => {
                    download_ok = true;
                    break;
                }
                Err(e) => {
                    log::warn!("[LlamaDownloader] {} failed: {}", mirror_name, e);
                    let _ = std::fs::remove_file(&temp_file);
                    if DOWNLOAD_ABORT.load(Ordering::SeqCst) {
                        break;
                    }
                }
            }
        }

        if DOWNLOAD_ABORT.load(Ordering::SeqCst) {
            let _ = std::fs::remove_dir_all(&temp_dir);
            let _ = std::fs::remove_dir_all(&bin_dir);
            *DOWNLOAD_FILE.lock().unwrap() = None;
            return Err("Download cancelled".to_string());
        }

        if !download_ok {
            let _ = std::fs::remove_dir_all(&temp_dir);
            emit_dl_progress(&app_handle, "llama-server", 0, 0, 0, "error", None);
            *DOWNLOAD_FILE.lock().unwrap() = None;
            return Err("All download mirrors failed".to_string());
        }

        // Extract
        log::info!("[LlamaDownloader] Extracting: {}", file_name);
        let extract_name = file_name.replace(".zip", "").replace(".tar.gz", "");
        let extract_dir = bin_dir.join(&extract_name);
        let _ = std::fs::create_dir_all(&extract_dir);

        if file_name.ends_with(".zip") {
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                let status = Command::new("powershell")
                    .args([
                        "-NoProfile",
                        "-Command",
                        &format!(
                            "Expand-Archive -Path '{}' -DestinationPath '{}' -Force",
                            temp_file.display(),
                            extract_dir.display()
                        ),
                    ])
                    .creation_flags(0x08000000)
                    .status()
                    .map_err(|e| format!("Extract failed: {}", e))?;
                if !status.success() {
                    return Err(format!(
                        "PowerShell Expand-Archive failed for {}",
                        file_name
                    ));
                }
            }
            #[cfg(not(windows))]
            return Err("ZIP extraction is only supported on Windows".to_string());
        } else {
            let status = Command::new("tar")
                .args([
                    "-xzf",
                    &temp_file.to_string_lossy(),
                    "-C",
                    &extract_dir.to_string_lossy(),
                ])
                .status()
                .map_err(|e| format!("Extract failed: {}", e))?;
            if !status.success() {
                return Err(format!("tar extraction failed for {}", file_name));
            }
        }

        let _ = std::fs::remove_file(&temp_file);
    }

    // Atomic swap: remove the old bin/ and rename bin.new/ → bin/.
    // Up to this point bin/ has been untouched, so a cancel anywhere
    // above leaves the user's previous install runnable. After this
    // point any error means the user has the new install but the old
    // one is gone — acceptable since extract has already succeeded.
    if bin_final.exists() {
        let _ = std::fs::remove_dir_all(&bin_final);
    }
    if let Err(e) = std::fs::rename(&bin_dir, &bin_final) {
        let _ = std::fs::remove_dir_all(&bin_dir);
        let _ = std::fs::remove_dir_all(&temp_dir);
        *DOWNLOAD_FILE.lock().unwrap() = None;
        return Err(format!("Failed to finalize install: {}", e));
    }

    #[cfg(not(windows))]
    {
        if let Some(exe_path) = LocalLlmServer::find_llama_server() {
            use std::os::unix::fs::PermissionsExt;
            let _ = std::fs::set_permissions(&exe_path, std::fs::Permissions::from_mode(0o755));
            log::info!(
                "[LlamaDownloader] Set executable permission: {}",
                exe_path.display()
            );
        }
    }

    let _ = std::fs::remove_dir_all(&temp_dir);
    emit_dl_progress(&app_handle, "llama-server", 100, 0, 0, "completed", None);

    *DOWNLOAD_FILE.lock().unwrap() = None;

    let install_path = LocalLlmServer::find_llama_server()
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default();
    log::info!("[LlamaDownloader] Installation complete: {}", install_path);
    Ok(install_path)
}

async fn download_engine_file(
    app_handle: &tauri::AppHandle,
    url: &str,
    dest: &PathBuf,
    completed_files: u32,
    total_files: u32,
) -> Result<(), String> {
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::limited(10))
        .build()
        .map_err(|e| e.to_string())?;

    let resp = client
        .get(url)
        .header("User-Agent", "Echobird/1.1")
        .send()
        .await
        .map_err(|e| e.to_string())?;

    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status().as_u16()));
    }

    let content_length = resp.content_length().unwrap_or(0);
    use std::io::Write;
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(dest)
        .map_err(|e| format!("File open error: {}", e))?;

    let mut downloaded: u64 = 0;
    let mut stream = resp.bytes_stream();
    let mut last_emit = std::time::Instant::now();

    while let Some(chunk) = stream.next().await {
        if DOWNLOAD_ABORT.load(Ordering::SeqCst) {
            return Err("Download cancelled".to_string());
        }
        let data = chunk.map_err(|e| format!("Stream error: {}", e))?;
        file.write_all(&data)
            .map_err(|e| format!("Write error: {}", e))?;
        downloaded += data.len() as u64;

        if last_emit.elapsed() >= std::time::Duration::from_millis(250) {
            let file_progress = if content_length > 0 {
                (downloaded as f64 / content_length as f64) * 100.0
            } else {
                0.0
            };
            let overall = ((completed_files as f64 + file_progress / 100.0) / total_files as f64
                * 100.0) as u32;
            emit_dl_progress(
                app_handle,
                "llama-server",
                overall,
                downloaded,
                content_length,
                "downloading",
                None,
            );
            last_emit = std::time::Instant::now();
        }
    }

    Ok(())
}

// ─── Engine status detection ───

#[allow(dead_code)]
fn check_python_package(package: &str) -> Option<String> {
    #[cfg(windows)]
    let result = {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        Command::new("pip3")
            .args(["show", package])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
    };
    #[cfg(not(windows))]
    let result = Command::new("pip3").args(["show", package]).output();

    if let Ok(out) = result {
        if out.status.success() {
            let stdout = String::from_utf8_lossy(&out.stdout);
            for line in stdout.lines() {
                if line.to_lowercase().starts_with("version:") {
                    return Some(line[8..].trim().to_string());
                }
            }
            return Some(String::new());
        }
    }
    None
}

/// Collect all installed binary directory names under the bin folder
fn get_installed_llama_binary_names() -> Vec<String> {
    let bin_dir = llama_install_dir().join("bin");
    if !bin_dir.exists() {
        return vec![];
    }
    let mut names: Vec<String> = Vec::new();
    if let Ok(entries) = std::fs::read_dir(&bin_dir) {
        for entry in entries.flatten() {
            if entry.path().is_dir() {
                let name = entry.file_name().to_string_lossy().to_string();
                if !name.is_empty() {
                    names.push(name);
                }
            }
        }
    }
    // Sort: llama-b* first, then cudart-*, then rest
    names.sort_by(|a, b| {
        let a_main = a.starts_with("llama-b");
        let b_main = b.starts_with("llama-b");
        b_main.cmp(&a_main).then(a.cmp(b))
    });
    names
}

/// Detect installed llama-server binary directory name for version parsing
fn get_installed_llama_binary_name() -> Option<String> {
    get_installed_llama_binary_names()
        .into_iter()
        .find(|n| n.starts_with("llama-b"))
}

/// Detect installed llama-server version from directory name (e.g. "llama-b7981-bin-win-cuda-...")
fn get_installed_llama_version() -> Option<String> {
    get_installed_llama_binary_name().and_then(|name| {
        if let Some(ver_end) = name.find("-bin-") {
            let ver = &name[6..ver_end]; // skip "llama-" prefix → already "bNNNN"
            Some(ver.to_string())
        } else {
            None
        }
    })
}

/// Get installation status for the specified runtime only (lazy — avoids unnecessary pip3 calls).
/// Pass `runtime_filter = None` to check all engines (legacy / admin use).
///
/// Page-mount entry point: also refreshes the engine version map from upstream
/// (GitHub for llama.cpp, PyPI for vllm/sglang) before answering. Without this
/// the "升级引擎" button never appears on first open — the cache is empty so
/// `get_engine_versions()` returns the fallback constant, which always matches
/// the installed binary, hiding any actual upstream update.
pub async fn get_local_engine_status(runtime_filter: Option<&str>) -> serde_json::Value {
    // Best-effort refresh; on network failure refresh_engine_versions falls
    // back to the cached/fallback map so the UI still loads.
    let versions = refresh_engine_versions().await;

    // ── llama-server (always cheap — binary lookup, no pip) ──────────────────
    let check_llama = runtime_filter.map(|r| r == "llama-server").unwrap_or(true);
    let llama_installed = if check_llama {
        LocalLlmServer::find_llama_server().is_some()
    } else {
        false
    };
    let installed_ver = if check_llama {
        get_installed_llama_version().unwrap_or_default()
    } else {
        String::new()
    };
    let binary_names = if check_llama {
        get_installed_llama_binary_names()
    } else {
        vec![]
    };
    let latest_llama = versions
        .get("llama-server")
        .map(|i| i.version.as_str())
        .unwrap_or(FALLBACK_LLAMA_VERSION);

    // ── vllm / sglang — Linux-only + only when explicitly selected ───────────
    let _check_vllm = runtime_filter.map(|r| r == "vllm").unwrap_or(false);
    let _check_sglang = runtime_filter.map(|r| r == "sglang").unwrap_or(false);

    #[cfg(target_os = "linux")]
    let vllm_version = if _check_vllm {
        check_python_package("vllm")
    } else {
        None
    };
    #[cfg(not(target_os = "linux"))]
    let vllm_version: Option<String> = None;

    #[cfg(target_os = "linux")]
    let sglang_version = if _check_sglang {
        check_python_package("sglang")
    } else {
        None
    };
    #[cfg(not(target_os = "linux"))]
    let sglang_version: Option<String> = None;

    let latest_vllm = versions.get("vllm").map(|i| i.version.clone());
    let latest_sglang = versions.get("sglang").map(|i| i.version.clone());

    serde_json::json!({
        "engines": [
            {
                "name": "llama-server",
                "installed": llama_installed,
                "version": installed_ver,
                "latestVersion": latest_llama,
                "installDir": llama_install_dir().to_string_lossy(),
                "binaryNames": binary_names
            },
            {
                "name": "vllm",
                "installed": vllm_version.is_some(),
                "version": vllm_version.clone().unwrap_or_default(),
                "latestVersion": latest_vllm
            },
            {
                "name": "sglang",
                "installed": sglang_version.is_some(),
                "version": sglang_version.clone().unwrap_or_default(),
                "latestVersion": latest_sglang
            }
        ]
    })
}

/// Install engine for local use. Routes by runtime:
/// - llama-server: binary download (auto-versioned from remote config)
/// - vllm / sglang: pip3 install
pub async fn install_local_engine(
    app_handle: tauri::AppHandle,
    runtime: String,
    override_version: Option<String>,
    override_cuda: Option<String>,
) -> Result<(), String> {
    match runtime.as_str() {
        "llama-server" => {
            // Atomic upgrade: don't pre-delete bin/. download_llama_server
            // stages the new install under bin.new/ and only swaps in on
            // successful extract, so a cancelled or failed download leaves
            // the user's existing bin/ untouched and runnable.
            //
            // overrides come from the Windows engine-version picker. When
            // present, persist them to the on-disk engine-versions.json
            // so detect-cuda sees the canonical CUDA version the user just
            // installed against.
            let v_clone = override_version.clone();
            let c_clone = override_cuda.clone();
            let result = download_llama_server(app_handle, override_version, override_cuda)
                .await
                .map(|_| ());
            if result.is_ok() {
                if let (Some(v), Some(c)) = (v_clone, c_clone) {
                    persist_engine_version("llama-server", &v, Some(&c));
                }
            }
            result
        }
        "vllm" => {
            #[cfg(target_os = "linux")]
            {
                install_pip_engine(&app_handle, "vllm", &runtime).await
            }
            #[cfg(not(target_os = "linux"))]
            {
                Err("vllm is only supported on Linux".to_string())
            }
        }
        "sglang" => {
            #[cfg(target_os = "linux")]
            {
                install_pip_engine(&app_handle, "sglang[all]", &runtime).await
            }
            #[cfg(not(target_os = "linux"))]
            {
                Err("sglang is only supported on Linux".to_string())
            }
        }
        other => Err(format!("Unknown runtime: {}", other)),
    }
}

/// Install a Python package via pip3, emitting download-progress events for UI
#[allow(dead_code)]
async fn install_pip_engine(
    app_handle: &tauri::AppHandle,
    package: &str,
    runtime: &str,
) -> Result<(), String> {
    let runtime = runtime.to_string();
    let package = package.to_string();
    let app = app_handle.clone();

    // Emit: installing started
    emit_dl_progress(&app, &runtime, 5, 0, 0, "installing", None);

    log::info!(
        "[EngineInstaller] pip3 install {} for runtime '{}'",
        package,
        runtime
    );

    // Pip install with PyPI mirrors (prefer China mirrors for faster access)
    let result = tokio::task::spawn_blocking({
        let package = package.clone();
        let runtime = runtime.clone();
        let app = app.clone();
        move || {
            // Try primary install
            #[cfg(windows)]
            let status = {
                use std::os::windows::process::CommandExt;
                const CREATE_NO_WINDOW: u32 = 0x08000000;
                Command::new("pip3")
                    .args([
                        "install", &package,
                        "--upgrade",
                        "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                        "--trusted-host", "pypi.tuna.tsinghua.edu.cn",
                    ])
                    .stdout(std::process::Stdio::piped())
                    .stderr(std::process::Stdio::piped())
                    .creation_flags(CREATE_NO_WINDOW)
                    .spawn()
            };
            #[cfg(not(windows))]
            let status = Command::new("pip3")
                .args([
                    "install", &package,
                    "--upgrade",
                    "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                    "--trusted-host", "pypi.tuna.tsinghua.edu.cn",
                ])
                .stdout(std::process::Stdio::piped())
                .stderr(std::process::Stdio::piped())
                .spawn();

            match status {
                Ok(mut child) => {
                    use std::io::{BufRead, BufReader};

                    // Emit progress=30 once child spawned
                    emit_dl_progress(&app, &runtime, 30, 0, 0, "installing", None);

                    // Stream stderr (pip outputs to stderr)
                    if let Some(stderr) = child.stderr.take() {
                        let reader = BufReader::new(stderr);
                        for line in reader.lines().map_while(Result::ok) {
                            log::info!("[pip3] {}", line);
                        }
                    }

                    match child.wait() {
                        Ok(status) if status.success() => Ok(()),
                        Ok(status) => {
                            // Fallback: retry with official PyPI
                            log::warn!("[EngineInstaller] Tsinghua mirror failed ({}), retrying with official PyPI", status);
                            emit_dl_progress(&app, &runtime, 50, 0, 0, "installing", None);
                            #[cfg(windows)]
                            let result2 = {
                                use std::os::windows::process::CommandExt;
                                const CREATE_NO_WINDOW: u32 = 0x08000000;
                                Command::new("pip3")
                                    .args(["install", &package, "--upgrade"])
                                    .creation_flags(CREATE_NO_WINDOW)
                                    .output()
                            };
                            #[cfg(not(windows))]
                            let result2 = Command::new("pip3")
                                .args(["install", &package, "--upgrade"])
                                .output();
                            match result2 {
                                Ok(out) if out.status.success() => Ok(()),
                                Ok(out) => Err(format!(
                                    "pip3 install failed:\n{}",
                                    String::from_utf8_lossy(&out.stderr)
                                )),
                                Err(e) => Err(format!("pip3 not found: {}", e)),
                            }
                        }
                        Err(e) => Err(format!("Failed to wait for pip3: {}", e)),
                    }
                }
                Err(e) => Err(format!("pip3 not found or failed to spawn: {}", e)),
            }
        }
    }).await.map_err(|e| format!("Task join error: {}", e))?;

    match result {
        Ok(()) => {
            log::info!("[EngineInstaller] {} installed successfully", package);
            emit_dl_progress(&app, &runtime, 100, 0, 0, "completed", None);
            Ok(())
        }
        Err(e) => {
            log::error!("[EngineInstaller] {} install failed: {}", package, e);
            emit_dl_progress(&app, &runtime, 0, 0, 0, "error", None);
            Err(e)
        }
    }
}