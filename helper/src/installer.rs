//! File operations, atomic installations, directory permission handling, and uninstallation.

use anyhow::{Context, Result};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use crate::manifest::{Manifest, ManifestAction, ManifestFile};

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

/// Determine default system font directory for the current operating system.
pub fn get_default_system_fonts_dir() -> PathBuf {
    if cfg!(target_os = "linux") {
        PathBuf::from("/usr/local/share/fonts/metaglyph")
    } else if cfg!(target_os = "macos") {
        PathBuf::from("/Library/Fonts")
    } else if cfg!(target_os = "windows") {
        let win_dir = std::env::var("WINDIR").unwrap_or_else(|_| r"C:\Windows".to_string());
        PathBuf::from(win_dir).join("Fonts")
    } else {
        PathBuf::from("/usr/local/share/fonts/metaglyph")
    }
}

/// Ensure directory exists with secure permissions (0755 on Unix).
pub fn ensure_directory_secure(dir: &Path) -> Result<()> {
    if !dir.exists() {
        fs::create_dir_all(dir)
            .with_context(|| format!("Failed to create destination directory: {:?}", dir))?;
    }

    #[cfg(unix)]
    {
        let permissions = fs::Permissions::from_mode(0o755);
        if let Err(e) = fs::set_permissions(dir, permissions) {
            eprintln!("Warning: could not set 0755 permissions on {:?}: {}", dir, e);
        }
    }

    Ok(())
}

/// Atomically copy a file to the destination path with secure permissions (0644 on Unix).
pub fn atomic_install_file(source: &Path, destination: &Path) -> Result<()> {
    let dest_dir = destination
        .parent()
        .ok_or_else(|| anyhow::anyhow!("Destination has no parent directory: {:?}", destination))?;

    ensure_directory_secure(dest_dir)?;

    // Reject if destination is a symlink
    if let Ok(meta) = destination.symlink_metadata() {
        if meta.file_type().is_symlink() {
            anyhow::bail!("Destination path {:?} is a symlink", destination);
        }
    }

    let temp_name = format!(
        ".metaglyph_tmp_{}_{}_{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0),
        destination
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("font.tmp")
    );
    let temp_path = dest_dir.join(temp_name);

    if let Ok(meta) = temp_path.symlink_metadata() {
        if meta.file_type().is_symlink() {
            anyhow::bail!("Temporary file path {:?} is a pre-existing symlink", temp_path);
        }
    }

    // Read and copy bytes
    let mut src_file = File::open(source)
        .with_context(|| format!("Failed to open source file: {:?}", source))?;
    let mut tmp_file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp_path)
        .with_context(|| format!("Failed to open temporary file: {:?}", temp_path))?;

    let mut buffer = [0u8; 64 * 1024];
    loop {
        let bytes_read = src_file
            .read(&mut buffer)
            .with_context(|| format!("Error reading from source file: {:?}", source))?;
        if bytes_read == 0 {
            break;
        }
        tmp_file
            .write_all(&buffer[..bytes_read])
            .with_context(|| format!("Error writing to temporary file: {:?}", temp_path))?;
    }

    tmp_file
        .sync_all()
        .with_context(|| format!("Failed to sync temporary file: {:?}", temp_path))?;
    drop(tmp_file);

    #[cfg(unix)]
    {
        let permissions = fs::Permissions::from_mode(0o644);
        if let Err(e) = fs::set_permissions(&temp_path, permissions) {
            eprintln!(
                "Warning: could not set 0644 permissions on {:?}: {}",
                temp_path, e
            );
        }
    }

    // Atomic rename
    fs::rename(&temp_path, destination).with_context(|| {
        format!(
            "Failed to atomically rename temporary file {:?} to destination {:?}",
            temp_path, destination
        )
    })?;

    Ok(())
}

/// Execute installation operations specified in the manifest.
pub fn execute_install(manifest: &Manifest) -> Result<Vec<String>> {
    let target_dir = manifest
        .target_dir
        .clone()
        .unwrap_or_else(get_default_system_fonts_dir);

    ensure_directory_secure(&target_dir)?;

    let mut installed_paths = Vec::new();

    for font in &manifest.fonts {
        for file_entry in &font.files {
            let source = file_entry.source_path.as_ref().ok_or_else(|| {
                anyhow::anyhow!("Missing source path for install in font '{}'", font.family_name)
            })?;

            let dest_path = if let Some(dest_p) = &file_entry.destination_path {
                if !dest_p.starts_with(&target_dir) {
                    anyhow::bail!(
                        "Destination path {:?} is not within target directory {:?}",
                        dest_p,
                        target_dir
                    );
                }
                dest_p.clone()
            } else if let Some(dest_name) = &file_entry.destination_filename {
                target_dir.join(dest_name)
            } else {
                let filename = source
                    .file_name()
                    .ok_or_else(|| anyhow::anyhow!("Source file has no filename: {:?}", source))?;
                target_dir.join(filename)
            };

            atomic_install_file(source, &dest_path)?;
            installed_paths.push(dest_path.to_string_lossy().to_string());
        }
    }

    Ok(installed_paths)
}

/// Execute uninstallation operations specified in the manifest.
pub fn execute_uninstall(manifest: &Manifest) -> Result<Vec<String>> {
    let target_dir = manifest
        .target_dir
        .clone()
        .unwrap_or_else(get_default_system_fonts_dir);

    let mut uninstalled_paths = Vec::new();

    for font in &manifest.fonts {
        for file_entry in &font.files {
            let dest_path = if let Some(dest_p) = &file_entry.destination_path {
                if !dest_p.starts_with(&target_dir) {
                    anyhow::bail!(
                        "Destination path {:?} is not within target directory {:?}",
                        dest_p,
                        target_dir
                    );
                }
                dest_p.clone()
            } else if let Some(dest_name) = &file_entry.destination_filename {
                target_dir.join(dest_name)
            } else {
                continue;
            };

            if dest_path.exists() {
                fs::remove_file(&dest_path).with_context(|| {
                    format!("Failed to remove font file: {:?}", dest_path)
                })?;
                uninstalled_paths.push(dest_path.to_string_lossy().to_string());
            }
        }
    }

    Ok(uninstalled_paths)
}
