// Codex binary resolution — port of tools/codex/lib/binary-resolver.cjs.
//
// Two flavors:
//
//   CLI (Codex CLI / `codex` command):
//     Codex v0.107+ ships as a Rust binary inside a platform-specific
//     npm package (`@openai/codex-<triple>`). Spawning the .cmd shim
//     directly drops TTY-ness inside the cmd /d /s /c wrapper and the
//     Rust TUI aborts with "stdin is not a terminal". We find the
//     bundled native exe under the npm install root and spawn it
//     directly; if the npm install isn't where we expect, we fall back
//     to the .cmd shim (which works in most non-TTY cases).
//
//   Desktop (ChatGPT desktop app — formerly "Codex Desktop"):
//     Independent of npm. Standalone installer drops a .exe at the
//     usual Programs path (named ChatGPT.exe post-merge, Codex.exe before);
//     Microsoft Store install exposes an alias under
//     %LOCALAPPDATA%\Microsoft\WindowsApps. macOS ships as a .app
//     bundle under /Applications (ChatGPT.app post-merge, Codex.app before).
//     Linux: no desktop build as of 2026-07.
//
// All public functions return Option<PathBuf> with `None` meaning
// "not found via the standard search path" — caller decides whether to
// fall back to a shell-resolved PATH lookup or to error out.

use std::path::PathBuf;
use std::time::Duration;

/// Resolve the standalone ChatGPT desktop binary path. Returns None on
/// Linux (no desktop build) or when the standard install locations
/// don't exist.
pub fn resolve_desktop_binary() -> Option<PathBuf> {
    let candidates: Vec<PathBuf> = {
        // `mut` is genuinely required on Windows / macOS where the cfg
        // blocks below push into `c`. On Linux there's no ChatGPT desktop
        // build, so neither cfg matches and `c` stays empty — clippy's
        // `unused_mut` is the expected state on that target, not a bug.
        #[allow(unused_mut)]
        let mut c: Vec<PathBuf> = Vec::new();

        #[cfg(windows)]
        {
            if let Ok(local_app_data) = std::env::var("LOCALAPPDATA") {
                // 1. Standalone installer default location. OpenAI merged the
                //    Codex desktop app into ChatGPT (late 2026); the install
                //    dir + exe are now ChatGPT. Keep the legacy Codex path as a
                //    fallback for users who haven't upgraded yet — first hit wins.
                c.push(
                    PathBuf::from(&local_app_data)
                        .join("Programs")
                        .join("ChatGPT")
                        .join("ChatGPT.exe"),
                );
                c.push(
                    PathBuf::from(&local_app_data)
                        .join("Programs")
                        .join("Codex")
                        .join("Codex.exe"),
                );
                // 2. Microsoft Store executable alias — Windows 10+ exposes a
                //    shim here that resolves to the Store package. Same rename:
                //    prefer ChatGPT.exe, fall back to the legacy Codex.exe alias.
                c.push(
                    PathBuf::from(&local_app_data)
                        .join("Microsoft")
                        .join("WindowsApps")
                        .join("ChatGPT.exe"),
                );
                c.push(
                    PathBuf::from(&local_app_data)
                        .join("Microsoft")
                        .join("WindowsApps")
                        .join("Codex.exe"),
                );
            }
            // 3. PATH lookup via `where` as a last resort.
            if let Some(p) = which_first("ChatGPT.exe").or_else(|| which_first("Codex.exe")) {
                c.push(p);
            }
        }

        #[cfg(target_os = "macos")]
        {
            // ChatGPT.app is the post-merge name; keep Codex.app for un-upgraded
            // installs. The executable inside the bundle mirrors the app name.
            c.push(PathBuf::from(
                "/Applications/ChatGPT.app/Contents/MacOS/ChatGPT",
            ));
            c.push(PathBuf::from(
                "/Applications/Codex.app/Contents/MacOS/Codex",
            ));
            if let Some(home) = dirs::home_dir() {
                c.push(
                    home.join("Applications")
                        .join("ChatGPT.app")
                        .join("Contents")
                        .join("MacOS")
                        .join("ChatGPT"),
                );
                c.push(
                    home.join("Applications")
                        .join("Codex.app")
                        .join("Contents")
                        .join("MacOS")
                        .join("Codex"),
                );
            }
        }

        // Linux: no ChatGPT desktop build exists; `c` stays empty.
        c
    };

    candidates.into_iter().find(|c| c.exists())
}

/// Resolve the `shell:AppsFolder\<AUMID>` launch URI for ChatGPT desktop
/// on Windows Store installs. Reads from `tools/chatgptdesktop/paths.json`
/// — the file shipped in the EchoBird tools directory.
#[cfg(windows)]
pub fn resolve_desktop_launch_uri(tools_dir: &std::path::Path) -> Option<String> {
    let path = tools_dir.join("chatgptdesktop").join("paths.json");
    let content = std::fs::read_to_string(&path).ok()?;
    let cfg: serde_json::Value = serde_json::from_str(&content).ok()?;
    cfg.get("launchUri")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
}

#[cfg(not(windows))]
pub fn resolve_desktop_launch_uri(_tools_dir: &std::path::Path) -> Option<String> {
    None
}

/// Find an installed Codex Store package family name by scanning
/// `packages_dir` (normally `%LOCALAPPDATA%\Packages`). A package family
/// name is `<Identity>_<PublisherHash>`; we match on the identity so the
/// lookup is independent of the publisher hash. Recognizes the stable
/// channel (`OpenAI.Codex`) and the beta channel (`OpenAI.CodexBeta`),
/// preferring stable when both are present.
#[cfg(windows)]
fn find_codex_store_family_in(packages_dir: &std::path::Path) -> Option<String> {
    let mut beta: Option<String> = None;
    for entry in std::fs::read_dir(packages_dir).ok()?.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        let identity = name
            .rsplit_once('_')
            .map(|(id, _)| id.to_string())
            .unwrap_or_else(|| name.clone());
        if identity == "OpenAI.Codex" {
            return Some(name); // stable channel preferred
        }
        if identity == "OpenAI.CodexBeta" && beta.is_none() {
            beta = Some(name);
        }
    }
    beta
}

/// Resolve the ChatGPT desktop launch URI from the actually-installed Store
/// package (stable or beta), independent of the publisher hash. Preferred
/// over the hardcoded `paths.json` URI: beta-channel users were previously
/// undetectable and launched the wrong (stable) AUMID. Returns None when no
/// Codex Store package is present.
///
/// Data source order: the registry-backed AppX inventory (`Get-AppxPackage`,
/// the authoritative source Windows itself uses and what CodexPlusPlus
/// consults) first, then a directory scan of `%LOCALAPPDATA%\Packages` as a
/// fallback when PowerShell is unavailable. Previously this only did the
/// directory scan - "guess path" mode that missed installs whose
/// package-data dir lives elsewhere; the registry query is authoritative.
#[cfg(windows)]
pub fn resolve_desktop_launch_uri_scanned() -> Option<String> {
    if let Some(pfn) = find_codex_store_family_via_appx() {
        return Some(format!("shell:AppsFolder\\{pfn}!App"));
    }
    let local = std::env::var("LOCALAPPDATA").ok()?;
    let packages = std::path::Path::new(&local).join("Packages");
    let pfn = find_codex_store_family_in(&packages)?;
    Some(format!("shell:AppsFolder\\{pfn}!App"))
}

#[cfg(not(windows))]
pub fn resolve_desktop_launch_uri_scanned() -> Option<String> {
    None
}

/// Query the AppX package inventory via `Get-AppxPackage` (backed by the
/// Windows registry / COM package store - the authoritative source, vs. a
/// filesystem directory scan). Returns the installed Codex Store package
/// family name (`<identity>_<publisherhash>`), preferring the stable
/// channel (`OpenAI.Codex`) over beta (`OpenAI.CodexBeta`), newest version
/// first. Returns None when PowerShell is missing/fails or no package is
/// installed.
#[cfg(windows)]
fn find_codex_store_family_via_appx() -> Option<String> {
    // Prefer stable: query OpenAI.Codex first, fall back to OpenAI.CodexBeta
    // only when stable isn't installed. Sort by version desc so the newest
    // install wins when several are present. Output is a single PFN line.
    let script = "if($p=Get-AppxPackage -Name OpenAI.Codex -ErrorAction SilentlyContinue | Sort-Object Version -Descending | Select-Object -First 1){$p.PackageFamilyName}elseif($p=Get-AppxPackage -Name OpenAI.CodexBeta -ErrorAction SilentlyContinue | Sort-Object Version -Descending | Select-Object -First 1){$p.PackageFamilyName}";
    // CREATE_NO_WINDOW: this proxy runs inside a GUI process, so spawning
    // powershell.exe without the flag flashes a console window (the
    // "terminal opens then closes before ChatGPT launches" symptom).
    // Same pattern as spawn_codex_desktop_exe / agent_tools / gpu.
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x08000000;
    let mut cmd = std::process::Command::new("powershell");
    cmd.args(["-NoProfile", "-NonInteractive", "-Command", script])
        .creation_flags(CREATE_NO_WINDOW);
    let output = cmd.output().ok()?;
    if !output.status.success() {
        return None;
    }
    parse_appx_package_family_name(&String::from_utf8_lossy(&output.stdout))
}

/// Parse the PackageFamilyName from `Get-AppxPackage` stdout. Pure string
/// logic so it's unit-testable on every platform without spawning PowerShell.
/// Accepts the first non-empty trimmed line and requires a `<identity>_<hash>`
/// shape so a malformed PowerShell response can't become a bogus AUMID.
#[cfg_attr(not(target_os = "windows"), allow(dead_code))]
fn parse_appx_package_family_name(output: &str) -> Option<String> {
    let pfn = output.lines().map(str::trim).find(|l| !l.is_empty())?;
    if pfn.contains('_') {
        Some(pfn.to_string())
    } else {
        None
    }
}

/// Resolve the native Codex CLI binary (the platform-specific Rust exe
/// shipped inside `@openai/codex-<triple>`). Returns None if neither
/// the global npm install nor any well-known fallback location holds
/// the expected file.
pub fn resolve_codex_cli_binary() -> Option<PathBuf> {
    let (plat_pkg, triple, exe_name) = match (std::env::consts::OS, std::env::consts::ARCH) {
        ("windows", "aarch64") => (
            "@openai/codex-win32-arm64",
            "aarch64-pc-windows-msvc",
            "codex.exe",
        ),
        ("windows", _) => (
            "@openai/codex-win32-x64",
            "x86_64-pc-windows-msvc",
            "codex.exe",
        ),
        ("macos", "aarch64") => (
            "@openai/codex-darwin-arm64",
            "aarch64-apple-darwin",
            "codex",
        ),
        ("macos", _) => ("@openai/codex-darwin-x64", "x86_64-apple-darwin", "codex"),
        ("linux", "aarch64") => (
            "@openai/codex-linux-arm64",
            "aarch64-unknown-linux-musl",
            "codex",
        ),
        ("linux", _) => (
            "@openai/codex-linux-x64",
            "x86_64-unknown-linux-musl",
            "codex",
        ),
        _ => return None,
    };

    let mut codex_pkg_roots: Vec<PathBuf> = Vec::new();

    // npm prefix dance: ask `which`/`where` for the codex shim, then
    // climb to its sibling `node_modules\@openai\codex` folder.
    let find_arg = if cfg!(windows) { "codex.cmd" } else { "codex" };
    if let Some(stub) = which_first(find_arg) {
        if let Some(npm_dir) = stub.parent() {
            codex_pkg_roots.push(npm_dir.join("node_modules").join("@openai").join("codex"));
            // Linux-style global install: /usr/bin/codex →
            // /usr/lib/node_modules/@openai/codex
            if let Some(parent) = npm_dir.parent() {
                codex_pkg_roots.push(
                    parent
                        .join("lib")
                        .join("node_modules")
                        .join("@openai")
                        .join("codex"),
                );
            }
        }
    }

    #[cfg(windows)]
    {
        let appdata = std::env::var("APPDATA")
            .or_else(|_| std::env::var("LOCALAPPDATA"))
            .ok();
        if let Some(appdata) = appdata {
            if appdata.len() > 2 {
                codex_pkg_roots.push(
                    PathBuf::from(appdata)
                        .join("npm")
                        .join("node_modules")
                        .join("@openai")
                        .join("codex"),
                );
            }
        }
    }

    #[cfg(not(windows))]
    {
        codex_pkg_roots.push(PathBuf::from("/usr/local/lib/node_modules/@openai/codex"));
        codex_pkg_roots.push(PathBuf::from("/usr/lib/node_modules/@openai/codex"));
        if let Some(home) = dirs::home_dir() {
            codex_pkg_roots.push(
                home.join(".npm-global")
                    .join("lib")
                    .join("node_modules")
                    .join("@openai")
                    .join("codex"),
            );
        }
    }

    for pkg_root in &codex_pkg_roots {
        let candidate = pkg_root
            .join("node_modules")
            .join(plat_pkg)
            .join("vendor")
            .join(triple)
            .join("codex")
            .join(exe_name);
        if candidate.exists() {
            return Some(candidate);
        }
    }
    None
}

/// Last-resort CLI fallback: locate the `codex.cmd` / `codex` shim
/// itself. Spawning via the shim works for non-TTY contexts and is
/// strictly better than failing to launch at all.
pub fn resolve_codex_cli_shim() -> Option<PathBuf> {
    let shim = if cfg!(windows) { "codex.cmd" } else { "codex" };

    // Direct file existence in the most common install locations first
    // (cheaper than spawning `where` / `which`).
    #[cfg(windows)]
    {
        let appdata = std::env::var("APPDATA")
            .or_else(|_| std::env::var("LOCALAPPDATA"))
            .ok();
        if let Some(appdata) = appdata {
            if appdata.len() > 2 {
                let candidate = PathBuf::from(appdata).join("npm").join(shim);
                if candidate.exists() {
                    return Some(candidate);
                }
            }
        }
    }
    #[cfg(not(windows))]
    {
        let candidate = PathBuf::from("/usr/local/bin").join(shim);
        if candidate.exists() {
            return Some(candidate);
        }
    }

    // PATH lookup.
    which_first(shim)
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/// Resolve the first PATH hit for `program` via the OS's `where` /
/// `which` command. We use the same approach as the .cjs version
/// (spawn the OS utility) rather than the `which` crate so we get
/// identical resolution semantics across the port.
fn which_first(program: &str) -> Option<PathBuf> {
    let (cmd, arg_to_find) = if cfg!(windows) {
        ("where", program)
    } else {
        ("which", program)
    };

    use std::process::{Command, Stdio};
    let mut command = Command::new(cmd);
    command
        .arg(arg_to_find)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());

    // Hide console window on Windows (this gets called from background
    // tasks, including the Tauri main process).
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = match command.spawn() {
        Ok(c) => c,
        Err(_) => return None,
    };

    // Bound the wait — `which` should be near-instant; `where` on
    // Windows occasionally stalls on broken PATH entries.
    let deadline = std::time::Instant::now() + Duration::from_secs(3);
    let output = loop {
        match child.try_wait() {
            Ok(Some(_status)) => break child.wait_with_output().ok()?,
            Ok(None) => {
                if std::time::Instant::now() >= deadline {
                    let _ = child.kill();
                    return None;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(_) => return None,
        }
    };

    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    stdout
        .lines()
        .map(str::trim)
        .find(|l| !l.is_empty())
        .map(PathBuf::from)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn which_first_finds_a_universal_command() {
        // Pick the OS's most-portable command. Skip if not found
        // (some sandboxed CI runners strip everything).
        let target = if cfg!(windows) { "cmd.exe" } else { "ls" };
        if let Some(p) = which_first(target) {
            assert!(
                p.to_string_lossy()
                    .to_lowercase()
                    .contains(target.trim_end_matches(".exe")),
                "got: {p:?}"
            );
        }
    }

    #[test]
    fn which_first_returns_none_for_nonexistent_program() {
        let result = which_first("this-program-definitely-does-not-exist-xyzzy-2026");
        assert!(result.is_none(), "got: {result:?}");
    }

    #[test]
    fn resolve_desktop_launch_uri_returns_none_for_missing_file() {
        let result =
            resolve_desktop_launch_uri(std::path::Path::new("/this/path/does/not/exist/anywhere"));
        assert!(result.is_none());
    }

    #[test]
    fn parse_appx_pfn_extracts_family_name_from_stdout() {
        // Get-AppxPackage emits the PFN on its own line (with a trailing
        // CRLF on Windows). We take the first non-empty trimmed line.
        assert_eq!(
            parse_appx_package_family_name("OpenAI.Codex_2p2nqsd0c76g0\r\n"),
            Some("OpenAI.Codex_2p2nqsd0c76g0".to_string())
        );
        // Leading blank line (PowerShell sometimes emits one) is skipped.
        assert_eq!(
            parse_appx_package_family_name("\n\nOpenAI.CodexBeta_ab12cd34ef56\n"),
            Some("OpenAI.CodexBeta_ab12cd34ef56".to_string())
        );
    }

    #[test]
    fn parse_appx_pfn_rejects_empty_and_malformed() {
        // Empty / whitespace-only output -> no package found.
        assert_eq!(parse_appx_package_family_name(""), None);
        assert_eq!(parse_appx_package_family_name("   \r\n  \n"), None);
        // A PFN must contain the `<identity>_<publisherhash>` underscore;
        // a bare token can't form a valid AUMID, so reject it rather than
        // emit a bogus shell:AppsFolder URI.
        assert_eq!(parse_appx_package_family_name("OpenAI"), None);
        assert_eq!(parse_appx_package_family_name("not-a-pfn"), None);
    }

    #[test]
    fn resolve_desktop_launch_uri_reads_uri_from_paths_json() {
        // Build a fake tools dir with chatgptdesktop/paths.json holding a
        // launchUri. Verify we extract it.
        use std::sync::atomic::{AtomicU64, Ordering};
        static N: AtomicU64 = AtomicU64::new(0);
        let dir = std::env::temp_dir().join(format!(
            "echobird_cbr_{}_{}",
            std::process::id(),
            N.fetch_add(1, Ordering::Relaxed)
        ));
        let cd_dir = dir.join("chatgptdesktop");
        std::fs::create_dir_all(&cd_dir).unwrap();
        std::fs::write(
            cd_dir.join("paths.json"),
            r#"{ "launchUri": "shell:AppsFolder\\OpenAI.Codex_xxx!App" }"#,
        )
        .unwrap();

        let got = resolve_desktop_launch_uri(&dir);
        #[cfg(windows)]
        assert_eq!(
            got.as_deref(),
            Some("shell:AppsFolder\\OpenAI.Codex_xxx!App")
        );
        // On non-Windows the function is hardcoded to None.
        #[cfg(not(windows))]
        assert!(got.is_none());

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[cfg(windows)]
    #[test]
    fn scan_detects_codex_beta_package_family() {
        use std::sync::atomic::{AtomicU64, Ordering};
        static N: AtomicU64 = AtomicU64::new(0);
        let pkgs = std::env::temp_dir().join(format!(
            "echobird_codexpkg_{}_{}",
            std::process::id(),
            N.fetch_add(1, Ordering::Relaxed)
        ));
        // Only the beta channel is installed (different publisher hash).
        std::fs::create_dir_all(pkgs.join("OpenAI.CodexBeta_9zz9zz9zz9zz9")).unwrap();
        std::fs::create_dir_all(pkgs.join("Microsoft.Unrelated_abcdefghijklm")).unwrap();

        let got = find_codex_store_family_in(&pkgs);
        assert_eq!(got.as_deref(), Some("OpenAI.CodexBeta_9zz9zz9zz9zz9"));

        let _ = std::fs::remove_dir_all(&pkgs);
    }

    #[cfg(windows)]
    #[test]
    fn scan_prefers_stable_codex_over_beta() {
        use std::sync::atomic::{AtomicU64, Ordering};
        static N: AtomicU64 = AtomicU64::new(0);
        let pkgs = std::env::temp_dir().join(format!(
            "echobird_codexpkg2_{}_{}",
            std::process::id(),
            N.fetch_add(1, Ordering::Relaxed)
        ));
        std::fs::create_dir_all(pkgs.join("OpenAI.CodexBeta_aaaaaaaaaaaaa")).unwrap();
        std::fs::create_dir_all(pkgs.join("OpenAI.Codex_bbbbbbbbbbbbb")).unwrap();

        let got = find_codex_store_family_in(&pkgs);
        assert_eq!(got.as_deref(), Some("OpenAI.Codex_bbbbbbbbbbbbb"));

        let _ = std::fs::remove_dir_all(&pkgs);
    }

    #[test]
    fn resolvers_are_callable_without_panicking() {
        // Smoke test: just make sure the resolvers don't panic when
        // Codex isn't installed. They legitimately may return None.
        let _ = resolve_desktop_binary();
        let _ = resolve_codex_cli_binary();
        let _ = resolve_codex_cli_shim();
    }
}
