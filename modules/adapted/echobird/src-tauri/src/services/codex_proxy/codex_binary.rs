// Native Codex CLI resolution for the runtime that needs the bundled Rust binary.
// Desktop detection and launch use the shared tool catalog.

use std::path::PathBuf;

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

    // Resolve the codex shim on PATH, then
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

    // Direct file existence in the most common install locations first.
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

/// Reuse the same in-process PATH resolver as the tool catalog.
fn which_first(program: &str) -> Option<PathBuf> {
    which::which(program).ok()
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
    fn resolvers_are_callable_without_panicking() {
        // Smoke test: just make sure the resolvers don't panic when
        // Codex isn't installed. They legitimately may return None.
        let _ = resolve_codex_cli_binary();
        let _ = resolve_codex_cli_shim();
    }
}