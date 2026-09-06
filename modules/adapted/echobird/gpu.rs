// GPU detection for all platforms
// Supports: NVIDIA, AMD ROCm, Intel XPU, Apple Silicon,
// and Chinese domestic: Iluvatar, Cambricon, Biren, KunlunXin
// Note: Moore Threads (MTT) cards are detected for display only; no special engine is bundled.

use super::settings::{load_model_settings, save_model_settings};
use super::types::{GpuInfo, SystemInfo};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::process::Command;

/// Get system information: OS, architecture, and GPU details
pub fn get_system_info() -> SystemInfo {
    let os = std::env::consts::OS.to_string();
    let arch = std::env::consts::ARCH.to_string();
    let gpu = detect_gpu();
    let has_gpu = gpu.is_some();
    let vendor = gpu
        .as_ref()
        .map(|g| classify_gpu_vendor(&g.gpu_name))
        .unwrap_or("none");
    SystemInfo {
        os,
        arch,
        gpu_name: gpu.as_ref().map(|g| g.gpu_name.clone()),
        gpu_vram_gb: gpu.as_ref().map(|g| g.gpu_vram_gb),
        has_gpu,
        has_nvidia_gpu: vendor == "nvidia",
        has_amd_gpu: vendor == "amd",
    }
}

/// Detect GPU and persist to settings
pub fn detect_gpu() -> Option<GpuInfo> {
    let info = detect_gpu_system();
    if let Some(ref gpu) = info {
        let mut settings = load_model_settings();
        settings.gpu_name = Some(gpu.gpu_name.clone());
        settings.gpu_vram_gb = Some(gpu.gpu_vram_gb);
        save_model_settings(&settings);
    }
    info
}

/// Get cached GPU info from settings (no re-detection)
pub fn get_gpu_info() -> Option<GpuInfo> {
    let settings = load_model_settings();
    match (settings.gpu_name, settings.gpu_vram_gb) {
        (Some(name), Some(vram)) if !name.is_empty() => Some(GpuInfo {
            gpu_name: name,
            gpu_vram_gb: vram,
        }),
        _ => None,
    }
}

/// Classify GPU vendor from (already-shortened) gpu_name string
fn classify_gpu_vendor(name: &str) -> &'static str {
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
        || n.starts_with("a10")
        || n.starts_with("l4")
        || n.starts_with("l40")
    {
        "nvidia"
    } else if n.starts_with("rx ") || n.contains(" rx ") || n.contains("radeon")
        || n.contains("vega") || n.contains("rdna") || n.contains("amd")
        || n.starts_with("mtt")    // Moore Threads
        || n.starts_with("bi-")    // Iluvatar CoreX
        || n.contains("mlu")       // Cambricon
        || n.starts_with("br")     // Biren
        || n.starts_with("k2") || n.starts_with("k3")
    // KunlunXin
    {
        "amd"
    } else if n.contains("arc") || n.contains("intel") || n.contains("uhd") || n.contains("iris") {
        "intel"
    } else {
        "other"
    }
}

/// Shorten verbose GPU names for display
fn shorten_gpu_name(name: &str) -> String {
    name
        // International brands
        .replace("NVIDIA GeForce ", "")
        .replace("NVIDIA RTX ", "RTX ")
        .replace("NVIDIA Tesla ", "Tesla ")
        .replace("NVIDIA ", "")
        .replace("AMD Radeon RX ", "RX ")
        .replace("AMD Radeon PRO ", "Radeon PRO ")
        .replace("AMD Radeon ", "")
        .replace("Intel(R) Arc\u{2122} ", "Arc ")
        .replace("Intel(R) Data Center GPU ", "Intel DC-GPU ")
        .replace("Intel(R) ", "Intel ")
        .replace("Apple ", "")
        // Chinese domestic brands
        .replace("Moore Threads ", "")
        .replace("Iluvatar CoreX ", "")
        .replace("Cambricon ", "")
        .replace("Biren ", "")
        .replace("KunlunXin ", "")
        // Cleanup
        .replace("(TM)", "")
        .replace("(R)", "")
        .replace("  ", " ")
        .trim()
        .to_string()
}

// ─── Platform-specific detection ───

#[cfg(windows)]
fn detect_gpu_system() -> Option<GpuInfo> {
    detect_gpu_nvidia_smi()
        .or_else(detect_gpu_rocm)
        .or_else(detect_gpu_wmic)
}

#[cfg(windows)]
fn detect_gpu_nvidia_smi() -> Option<GpuInfo> {
    let output = Command::new("nvidia-smi")
        .args([
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ])
        .creation_flags(0x08000000)
        .output()
        .ok()?;

    if !output.status.success() {
        return None;
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    log::info!("[GPU] nvidia-smi output: {}", stdout.trim());

    let (display_name, total_vram_gb) = aggregate_nvidia_gpus_from_smi_output(&stdout)?;
    log::info!(
        "[GPU] nvidia-smi aggregated: {} ({:.1} GB total VRAM)",
        display_name,
        total_vram_gb
    );
    Some(GpuInfo {
        gpu_name: display_name,
        gpu_vram_gb: total_vram_gb,
    })
}

#[cfg(windows)]
fn detect_gpu_wmic() -> Option<GpuInfo> {
    let output = Command::new("wmic")
        .args([
            "path",
            "win32_VideoController",
            "get",
            "Name,AdapterRAM",
            "/format:csv",
        ])
        .creation_flags(0x08000000)
        .output()
        .ok()?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    log::info!("[GPU] wmic output: {}", stdout.trim());

    let mut best_name = String::new();
    let mut best_vram: u64 = 0;

    for line in stdout.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with("Node") {
            continue;
        }
        let parts: Vec<&str> = line.split(',').collect();
        if parts.len() >= 3 {
            let adapter_ram: u64 = parts[1].trim().parse().unwrap_or(0);
            let name = parts[2].trim().to_string();
            if adapter_ram > best_vram && !name.is_empty() {
                best_vram = adapter_ram;
                best_name = name;
            }
        }
    }

    if best_name.is_empty() {
        return None;
    }

    let vram_gb = best_vram as f64 / (1024.0 * 1024.0 * 1024.0);
    let vram_gb = (vram_gb * 10.0).round() / 10.0;
    let short_name = shorten_gpu_name(&best_name);
    log::info!(
        "[GPU] wmic detected: {} ({:.1} GB VRAM)",
        short_name,
        vram_gb
    );

    Some(GpuInfo {
        gpu_name: short_name,
        gpu_vram_gb: vram_gb,
    })
}

#[cfg(windows)]
fn detect_gpu_rocm() -> Option<GpuInfo> {
    let out = Command::new("rocm-smi")
        .args(["--showmeminfo", "vram", "--showname", "--csv"])
        .creation_flags(0x08000000)
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout);
    for line in s.lines().skip(1) {
        let p: Vec<&str> = line.split(',').map(|x| x.trim()).collect();
        if p.len() >= 3 {
            let mb: f64 = p[2].parse().unwrap_or(0.0);
            if mb > 0.0 {
                let gb = (mb / 1024.0 * 10.0).round() / 10.0;
                return Some(GpuInfo {
                    gpu_name: shorten_gpu_name(p[1]),
                    gpu_vram_gb: gb,
                });
            }
        }
    }
    None
}

#[cfg(not(windows))]
fn detect_gpu_system() -> Option<GpuInfo> {
    None.or_else(detect_gpu_nvidia_smi_unix)
        .or_else(detect_gpu_rocm)
        .or_else(detect_gpu_intel_xpu)
        .or_else(detect_gpu_apple)
        .or_else(detect_gpu_iluvatar)
        .or_else(detect_gpu_cambricon)
        .or_else(detect_gpu_biren)
        .or_else(detect_gpu_kunlunxin)
}

#[cfg(not(windows))]
fn detect_gpu_nvidia_smi_unix() -> Option<GpuInfo> {
    let out = Command::new("nvidia-smi")
        .args([
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&out.stdout);
    let (display_name, total_vram_gb) = aggregate_nvidia_gpus_from_smi_output(&stdout)?;
    log::info!(
        "[GPU] nvidia-smi aggregated: {} ({:.1} GB total VRAM)",
        display_name,
        total_vram_gb
    );
    Some(GpuInfo {
        gpu_name: display_name,
        gpu_vram_gb: total_vram_gb,
    })
}

#[cfg(not(windows))]
fn detect_gpu_rocm() -> Option<GpuInfo> {
    let out = Command::new("rocm-smi")
        .args(["--showmeminfo", "vram", "--showname", "--csv"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout);
    for line in s.lines().skip(1) {
        let p: Vec<&str> = line.split(',').map(|x| x.trim()).collect();
        if p.len() >= 3 {
            let mb: f64 = p[2].parse().unwrap_or(0.0);
            if mb > 0.0 {
                let gb = (mb / 1024.0 * 10.0).round() / 10.0;
                let name = shorten_gpu_name(p[1]);
                log::info!("[GPU] rocm-smi: {} ({:.1}GB)", name, gb);
                return Some(GpuInfo {
                    gpu_name: name,
                    gpu_vram_gb: gb,
                });
            }
        }
    }
    None
}

#[cfg(not(windows))]
fn detect_gpu_intel_xpu() -> Option<GpuInfo> {
    let out = Command::new("xpu-smi")
        .args(["discovery", "-j"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let json: serde_json::Value = serde_json::from_slice(&out.stdout).ok()?;
    let dev = json.get("device_list")?.as_array()?.first()?;
    let name = dev
        .get("device_name")
        .and_then(|v| v.as_str())
        .unwrap_or("Intel GPU");
    let mb = dev
        .get("memory_physical_size")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    if mb > 0.0 {
        let gb = (mb / 1024.0 * 10.0).round() / 10.0;
        log::info!("[GPU] xpu-smi: {} ({:.1}GB)", name, gb);
        return Some(GpuInfo {
            gpu_name: shorten_gpu_name(name),
            gpu_vram_gb: gb,
        });
    }
    None
}

#[cfg(target_os = "macos")]
fn detect_gpu_apple() -> Option<GpuInfo> {
    let out = Command::new("system_profiler")
        .args(["SPDisplaysDataType", "-json"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let json: serde_json::Value = serde_json::from_slice(&out.stdout).ok()?;
    for d in json.get("SPDisplaysDataType")?.as_array()? {
        let name = d.get("sppci_model").and_then(|v| v.as_str()).unwrap_or("");
        if name.is_empty() {
            continue;
        }
        let vraw = d
            .get("spdisplays_vram")
            .and_then(|v| v.as_str())
            .unwrap_or("0 MB");
        let mb: f64 = vraw
            .split_whitespace()
            .next()
            .and_then(|n| n.parse().ok())
            .unwrap_or(0.0);
        let mut gb = if mb >= 1024.0 { mb / 1024.0 } else { mb };
        // Apple Silicon uses unified memory and reports no dedicated VRAM here
        // (spdisplays_vram is absent → parses to 0). The GPU shares system RAM,
        // so fall back to ~75% of total RAM as the Metal working-set budget — a
        // real, conservative number for the UI label + model-fit heuristic
        // instead of 0 (which made every model look like it wouldn't fit and is
        // unrelated to whether Metal can be used).
        if gb <= 0.0 {
            gb = mac_unified_memory_gb()
                .map(|total| total * 0.75)
                .unwrap_or(0.0);
        }
        let gb = (gb * 10.0).round() / 10.0;
        log::info!("[GPU] Apple: {} ({:.1}GB)", name, gb);
        return Some(GpuInfo {
            gpu_name: shorten_gpu_name(name),
            gpu_vram_gb: gb,
        });
    }
    None
}

/// Total physical RAM in GiB on macOS via `sysctl hw.memsize`. Used as the
/// basis for the Metal working-set budget on Apple Silicon, where the GPU
/// shares unified memory and reports no dedicated VRAM. Returns `None` if
/// sysctl is unavailable or its output can't be parsed.
#[cfg(target_os = "macos")]
fn mac_unified_memory_gb() -> Option<f64> {
    let out = Command::new("sysctl")
        .args(["-n", "hw.memsize"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let bytes: f64 = String::from_utf8_lossy(&out.stdout).trim().parse().ok()?;
    if bytes <= 0.0 {
        return None;
    }
    Some(bytes / (1024.0 * 1024.0 * 1024.0))
}

#[cfg(all(not(windows), not(target_os = "macos")))]
fn detect_gpu_apple() -> Option<GpuInfo> {
    None
}

#[cfg(not(windows))]
fn detect_gpu_iluvatar() -> Option<GpuInfo> {
    let out = Command::new("ixsmi")
        .args(["-q", "--display=MEMORY"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let name_o = Command::new("ixsmi")
        .args(["-q", "--display=NAME"])
        .output()
        .ok()?;
    let gb = parse_vram_mb_line(&String::from_utf8_lossy(&out.stdout))?;
    let name = parse_name_colon(&String::from_utf8_lossy(&name_o.stdout))
        .unwrap_or_else(|| "Iluvatar CoreX".to_string());
    log::info!("[GPU] ixsmi: {} ({:.1}GB)", name, gb);
    Some(GpuInfo {
        gpu_name: shorten_gpu_name(&name),
        gpu_vram_gb: gb,
    })
}

#[cfg(not(windows))]
fn detect_gpu_cambricon() -> Option<GpuInfo> {
    let out = Command::new("cnmon").args(["info", "-j"]).output().ok()?;
    if !out.status.success() {
        return None;
    }
    let json: serde_json::Value = serde_json::from_slice(&out.stdout).ok()?;
    let dev = json.get("device")?.as_array()?.first()?;
    let name = dev
        .get("Product Name")
        .or_else(|| dev.get("name"))
        .and_then(|v| v.as_str())
        .unwrap_or("Cambricon MLU");
    let mb = dev
        .get("Memory Info")
        .and_then(|m| m.get("Total"))
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    if mb > 0.0 {
        let gb = (mb / 1024.0 * 10.0).round() / 10.0;
        log::info!("[GPU] cnmon: {} ({:.1}GB)", name, gb);
        return Some(GpuInfo {
            gpu_name: shorten_gpu_name(name),
            gpu_vram_gb: gb,
        });
    }
    None
}

#[cfg(not(windows))]
fn detect_gpu_biren() -> Option<GpuInfo> {
    let out = Command::new("brsmi")
        .args(["-q", "--display=MEMORY"])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let name_o = Command::new("brsmi")
        .args(["-q", "--display=NAME"])
        .output()
        .ok()?;
    let gb = parse_vram_mb_line(&String::from_utf8_lossy(&out.stdout))?;
    let name = parse_name_colon(&String::from_utf8_lossy(&name_o.stdout))
        .unwrap_or_else(|| "Biren BR".to_string());
    log::info!("[GPU] brsmi: {} ({:.1}GB)", name, gb);
    Some(GpuInfo {
        gpu_name: shorten_gpu_name(&name),
        gpu_vram_gb: gb,
    })
}

#[cfg(not(windows))]
fn detect_gpu_kunlunxin() -> Option<GpuInfo> {
    let out = Command::new("kunlunxin-smi")
        .args([
            "--query-xpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ])
        .output()
        .ok()?;
    if !out.status.success() {
        return None;
    }
    let s = String::from_utf8_lossy(&out.stdout);
    let line = s.lines().next()?.trim().to_string();
    let p: Vec<&str> = line.split(',').map(|x| x.trim()).collect();
    if p.len() >= 2 {
        let mb: f64 = p[1].parse().unwrap_or(0.0);
        if mb > 0.0 {
            let gb = (mb / 1024.0 * 10.0).round() / 10.0;
            log::info!("[GPU] kunlunxin-smi: {} ({:.1}GB)", p[0], gb);
            return Some(GpuInfo {
                gpu_name: shorten_gpu_name(p[0]),
                gpu_vram_gb: gb,
            });
        }
    }
    None
}

#[cfg(not(windows))]
fn parse_vram_mb_line(text: &str) -> Option<f64> {
    for line in text.lines() {
        let lower = line.to_lowercase();
        if lower.contains("total") && (lower.contains("mib") || lower.contains("mb")) {
            if let Some(n) = line.split_whitespace().find(|s| s.parse::<f64>().is_ok()) {
                let mb: f64 = n.parse().ok()?;
                if mb > 0.0 {
                    return Some((mb / 1024.0 * 10.0).round() / 10.0);
                }
            }
        }
    }
    None
}

#[cfg(not(windows))]
fn parse_name_colon(text: &str) -> Option<String> {
    text.lines()
        .find(|l| {
            let lower = l.to_lowercase();
            lower.contains("product name") || lower.contains("device name")
        })
        .and_then(|l| l.split(':').nth(1))
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
}

// ═══════════════════════════════════════════════════════════════════
//  Multi-GPU detection — counts how many physical NVIDIA cards are
//  available so `local_llm::server` can inject tensor-parallel /
//  tensor-split args at spawn time. Zero-UI feature: no toggle, no
//  user-visible setting; the count drives the behaviour automatically.
//  Returns 0 when nvidia-smi is missing or fails (single-GPU /
//  AMD-only / no-GPU users see no change in behaviour).
// ═══════════════════════════════════════════════════════════════════

/// Count of NVIDIA GPUs reported by `nvidia-smi`. Returns 0 if the
/// tool is unavailable or reports no devices. Used by
/// `local_llm::server::start` to choose between single-GPU defaults
/// and tensor-parallel multi-GPU args.
pub fn detect_nvidia_gpu_count() -> usize {
    let mut cmd = Command::new("nvidia-smi");
    cmd.args([
        "--query-gpu=name,memory.total",
        "--format=csv,noheader,nounits",
    ]);
    #[cfg(windows)]
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW

    let output = match cmd.output() {
        Ok(o) => o,
        Err(_) => return 0,
    };
    if !output.status.success() {
        return 0;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    count_nvidia_gpus_from_smi_output(&stdout)
}

/// Pure parser split out from `detect_nvidia_gpu_count` so it's
/// testable without spawning a real `nvidia-smi`. Each non-empty
/// non-whitespace line in the CSV output is one GPU.
pub(super) fn count_nvidia_gpus_from_smi_output(stdout: &str) -> usize {
    stdout
        .lines()
        .filter(|line| !line.trim().is_empty())
        .count()
}

/// Aggregate every NVIDIA card reported by `nvidia-smi` into a single
/// display string + total VRAM, so multi-GPU hosts see the SUM
/// (instead of being underestimated by reading only card 0). Powers
/// the UI's "GPU: X, NG" label and the `getVramFitness` model-fit
/// heuristic, both of which read `SystemInfo.gpu_vram_gb`.
///
/// Returns `None` when no valid line is found (no GPU / malformed
/// output / nvidia-smi missing).
///
/// Display-name rules:
/// - 1 card → just that card's shortened name ("RTX 4090")
/// - N homogeneous cards → "RTX 4090 ×N"
/// - N heterogeneous cards → "RTX 5080 + RTX 5060 Ti" (joined with `+`)
pub(super) fn aggregate_nvidia_gpus_from_smi_output(stdout: &str) -> Option<(String, f64)> {
    let mut names: Vec<String> = Vec::new();
    let mut total_mb: f64 = 0.0;

    for line in stdout.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
        if parts.len() < 2 {
            continue;
        }
        let vram_mb: f64 = parts[1].parse().unwrap_or(0.0);
        if vram_mb <= 0.0 {
            continue;
        }
        total_mb += vram_mb;
        names.push(shorten_gpu_name(parts[0]));
    }

    if names.is_empty() || total_mb <= 0.0 {
        return None;
    }

    let total_gb = (total_mb / 1024.0 * 10.0).round() / 10.0;
    let display_name = if names.len() == 1 {
        names.into_iter().next().unwrap()
    } else if names.iter().all(|n| n == &names[0]) {
        // Homogeneous rig (e.g. 4× A100, 8× H100) — compact suffix
        // reads better than repeating the name. The "×N" form is what
        // datacenter shorthand uses.
        format!("{} ×{}", names[0], names.len())
    } else {
        // Heterogeneous (consumer setup, e.g. RTX 5080 + RTX 5060 Ti).
        // Joined with " + " so each card stays explicit in the UI.
        names.join(" + ")
    };
    Some((display_name, total_gb))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn count_zero_for_empty_output() {
        assert_eq!(count_nvidia_gpus_from_smi_output(""), 0);
        assert_eq!(count_nvidia_gpus_from_smi_output("\n\n  \n"), 0);
    }

    #[test]
    fn count_one_for_single_card() {
        // Real nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits
        // output for one card. Format is "<name>, <MiB>".
        let stdout = "NVIDIA GeForce RTX 4090, 24564\n";
        assert_eq!(count_nvidia_gpus_from_smi_output(stdout), 1);
    }

    #[test]
    fn count_n_for_homogeneous_multi_gpu() {
        // Common model-factory setup: 2× RTX 4090.
        let stdout = "NVIDIA GeForce RTX 4090, 24564\nNVIDIA GeForce RTX 4090, 24564\n";
        assert_eq!(count_nvidia_gpus_from_smi_output(stdout), 2);

        // 4× A100 — datacenter setup.
        let stdout = "NVIDIA A100-SXM4-80GB, 81251\n".repeat(4);
        assert_eq!(count_nvidia_gpus_from_smi_output(&stdout), 4);

        // 8× H100 — large training rig.
        let stdout = "NVIDIA H100 80GB HBM3, 81559\n".repeat(8);
        assert_eq!(count_nvidia_gpus_from_smi_output(&stdout), 8);
    }

    #[test]
    fn count_n_for_heterogeneous_multi_gpu() {
        // Mixed cards on the same box — counter just needs the line count,
        // it doesn't care about per-card details.
        let stdout = "NVIDIA GeForce RTX 4090, 24564\nNVIDIA GeForce RTX 3090, 24268\n";
        assert_eq!(count_nvidia_gpus_from_smi_output(stdout), 2);
    }

    #[test]
    fn count_ignores_trailing_and_blank_lines() {
        // nvidia-smi versions vary on trailing newline behaviour; both
        // shapes should yield the same count.
        let with_trailing = "NVIDIA GeForce RTX 4090, 24564\nNVIDIA GeForce RTX 3090, 24268\n\n";
        let without_trailing = "NVIDIA GeForce RTX 4090, 24564\nNVIDIA GeForce RTX 3090, 24268";
        assert_eq!(count_nvidia_gpus_from_smi_output(with_trailing), 2);
        assert_eq!(count_nvidia_gpus_from_smi_output(without_trailing), 2);
    }

    // ─── aggregate_nvidia_gpus_from_smi_output ───
    //
    // Same fixtures as the count_ tests, but now asserting the full
    // (display_name, total_vram_gb) tuple that drives SystemInfo.

    #[test]
    fn aggregate_returns_none_for_empty_or_garbage() {
        assert_eq!(aggregate_nvidia_gpus_from_smi_output(""), None);
        assert_eq!(aggregate_nvidia_gpus_from_smi_output("\n\n\n"), None);
        // Single-field line — not enough commas to parse name + memory.
        assert_eq!(aggregate_nvidia_gpus_from_smi_output("just a name\n"), None);
        // Non-numeric memory column.
        assert_eq!(
            aggregate_nvidia_gpus_from_smi_output("NVIDIA GeForce RTX 4090, oops\n"),
            None
        );
    }

    #[test]
    fn aggregate_single_card_keeps_unchanged_shape() {
        // Single-GPU users see exactly what they saw before this change.
        let (name, vram) =
            aggregate_nvidia_gpus_from_smi_output("NVIDIA GeForce RTX 4090, 24564\n").unwrap();
        assert_eq!(name, "RTX 4090");
        assert!((vram - 24.0).abs() < 0.1, "got: {vram}");
    }

    #[test]
    fn aggregate_homogeneous_multi_gpu_uses_compact_suffix() {
        // 2× RTX 4090 — datacenter shorthand "RTX 4090 ×2".
        let (name, vram) = aggregate_nvidia_gpus_from_smi_output(
            "NVIDIA GeForce RTX 4090, 24564\nNVIDIA GeForce RTX 4090, 24564\n",
        )
        .unwrap();
        assert_eq!(name, "RTX 4090 ×2");
        assert!((vram - 48.0).abs() < 0.1, "got: {vram}");

        // 4× A100 — large training rig.
        let stdout = "NVIDIA A100-SXM4-80GB, 81251\n".repeat(4);
        let (name, vram) = aggregate_nvidia_gpus_from_smi_output(&stdout).unwrap();
        assert_eq!(name, "A100-SXM4-80GB ×4");
        // 81251 MiB × 4 / 1024 ≈ 317.4 GiB; rounded to 1 decimal.
        assert!(vram > 315.0 && vram < 320.0, "got: {vram}");
    }

    #[test]
    fn aggregate_heterogeneous_multi_gpu_joins_with_plus() {
        // yby1025's real setup (issue #83): 5080 (16GB) + 5060 Ti (16GB).
        // Total 32GB — the whole point of supporting multi-GPU sum.
        let (name, vram) = aggregate_nvidia_gpus_from_smi_output(
            "NVIDIA GeForce RTX 5080, 16384\nNVIDIA GeForce RTX 5060 Ti, 16384\n",
        )
        .unwrap();
        assert_eq!(name, "RTX 5080 + RTX 5060 Ti");
        assert!((vram - 32.0).abs() < 0.1, "got: {vram}");
    }

    #[test]
    fn aggregate_skips_malformed_lines_but_keeps_valid_ones() {
        // Real nvidia-smi shouldn't emit garbage lines, but defensive
        // parsing is cheap. One valid line + one malformed → just the
        // valid line wins.
        let (name, vram) = aggregate_nvidia_gpus_from_smi_output(
            "NVIDIA GeForce RTX 4090, 24564\ngarbage line with no comma\n",
        )
        .unwrap();
        assert_eq!(name, "RTX 4090");
        assert!((vram - 24.0).abs() < 0.1);
    }
}
