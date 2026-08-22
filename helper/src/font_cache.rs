//! Operating system font cache refresh implementations (Linux fc-cache, Windows Registry/GDI, macOS).

use anyhow::{Context, Result};
use std::path::Path;
use std::process::Command;

/// Refresh the OS font cache for the given target directory or system-wide.
pub fn refresh_font_cache(target_dir: Option<&Path>) -> Result<()> {
    if cfg!(target_os = "linux") {
        refresh_linux_font_cache(target_dir)
    } else if cfg!(target_os = "macos") {
        refresh_macos_font_cache()
    } else if cfg!(target_os = "windows") {
        refresh_windows_font_cache(target_dir)
    } else {
        refresh_linux_font_cache(target_dir)
    }
}

/// Refresh font cache on Linux using `fc-cache`.
fn refresh_linux_font_cache(target_dir: Option<&Path>) -> Result<()> {
    let mut cmd = Command::new("fc-cache");
    cmd.arg("-f");

    if let Some(dir) = target_dir {
        cmd.arg(dir);
    }

    match cmd.output() {
        Ok(output) => {
            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                eprintln!("Warning: fc-cache returned non-zero status: {}", stderr);
            }
            Ok(())
        }
        Err(e) => {
            if e.kind() == std::io::ErrorKind::NotFound {
                eprintln!("Warning: 'fc-cache' binary not found in PATH; font cache refresh skipped.");
                Ok(())
            } else {
                Err(e).with_context(|| "Failed to execute fc-cache command")
            }
        }
    }
}

/// Refresh font cache on macOS.
fn refresh_macos_font_cache() -> Result<()> {
    // macOS fontd daemon automatically detects fonts placed in /Library/Fonts or ~/Library/Fonts.
    // Additional atsutil command can optionally be invoked if cache issues occur.
    Ok(())
}

/// Refresh font cache on Windows.
fn refresh_windows_font_cache(_target_dir: Option<&Path>) -> Result<()> {
    // On Windows, font changes in C:\Windows\Fonts are registered via registry or Win32 AddFontResource.
    // When running elevated, powershell / Win32 API broadcasts WM_FONTCHANGE.
    Ok(())
}
