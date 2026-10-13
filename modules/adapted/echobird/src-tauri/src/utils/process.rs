//! Background commands share Windows console suppression. User-requested
//! interactive terminal launches stay in process_manager.
use std::{ffi::OsStr, process::Command};

pub fn command(program: impl AsRef<OsStr>) -> Command {
    #[allow(unused_mut)] // Windows adds creation flags; other platforms keep std defaults.
    let mut command = Command::new(program);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    command
}

pub fn async_command(program: impl AsRef<OsStr>) -> tokio::process::Command {
    command(program).into()
}

#[cfg(all(test, windows))]
mod tests {
    #[tokio::test]
    async fn background_children_have_no_console_and_preserve_output_and_status() {
        let script = "Add-Type 'using System; using System.Runtime.InteropServices; public class Probe { [DllImport(\"kernel32.dll\")] public static extern IntPtr GetConsoleWindow(); }'; [Probe]::GetConsoleWindow().ToInt64(); exit 7";
        let args = ["-NoProfile", "-NonInteractive", "-Command", script];
        let sync = super::command("powershell.exe")
            .args(args)
            .output()
            .unwrap();
        let asynchronous = super::async_command("powershell.exe")
            .args(args)
            .output()
            .await
            .unwrap();
        for result in [sync, asynchronous] {
            assert_eq!(result.status.code(), Some(7));
            assert_eq!(String::from_utf8_lossy(&result.stdout).trim(), "0");
        }
    }
}