//! Manifest parsing, data structures, and security validation for metaglyph-helper.

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

/// Action to perform: installation or uninstallation of font files.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ManifestAction {
    Install,
    Uninstall,
}

/// An individual font file entry in the manifest.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManifestFile {
    /// Source file path on disk (required for install action).
    #[serde(default)]
    pub source_path: Option<PathBuf>,
    /// Clean destination filename (e.g. "JetBrainsMono-Regular.ttf").
    #[serde(default)]
    pub destination_filename: Option<String>,
    /// Direct destination file path on disk (optional).
    #[serde(default)]
    pub destination_path: Option<PathBuf>,
}

/// A font family entry containing multiple variant files.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManifestFont {
    pub family_name: String,
    pub files: Vec<ManifestFile>,
}

/// Root IPC JSON manifest definition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Manifest {
    #[serde(default = "default_manifest_version")]
    pub version: u32,
    pub action: ManifestAction,
    #[serde(default = "default_target_scope")]
    pub target_scope: String,
    #[serde(default)]
    pub target_dir: Option<PathBuf>,
    pub fonts: Vec<ManifestFont>,
}

fn default_manifest_version() -> u32 {
    1
}

fn default_target_scope() -> String {
    "system".to_string()
}

/// Structured JSON status report returned by the helper binary on stdout.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HelperResult {
    pub success: bool,
    pub action: String,
    pub installed_files: Vec<String>,
    pub uninstalled_files: Vec<String>,
    pub errors: Vec<String>,
    pub message: String,
}

impl HelperResult {
    pub fn success(
        action: &str,
        installed: Vec<String>,
        uninstalled: Vec<String>,
        message: String,
    ) -> Self {
        Self {
            success: true,
            action: action.to_string(),
            installed_files: installed,
            uninstalled_files: uninstalled,
            errors: Vec::new(),
            message,
        }
    }

    pub fn failure(action: &str, errors: Vec<String>, message: String) -> Self {
        Self {
            success: false,
            action: action.to_string(),
            installed_files: Vec::new(),
            uninstalled_files: Vec::new(),
            errors,
            message,
        }
    }
}

/// Verify that a file contains valid font header magic bytes (TTF, OTF, TTC, WOFF, WOFF2).
pub fn verify_font_magic_bytes(path: &Path) -> Result<()> {
    let mut file = File::open(path)
        .with_context(|| format!("Failed to open font file for magic byte validation: {:?}", path))?;

    let mut header = [0u8; 4];
    file.read_exact(&mut header)
        .with_context(|| format!("Failed to read font magic bytes from: {:?}", path))?;

    let is_valid = matches!(
        &header,
        [0x00, 0x01, 0x00, 0x00] // TrueType
            | b"OTTO"            // OpenType with CFF
            | b"ttcf"            // TrueType Collection
            | b"true"            // Mac TrueType
            | b"typ1"            // PostScript Type 1
            | b"wOFF"            // WOFF 1.0
            | b"wOF2"            // WOFF 2.0
    );

    if !is_valid {
        bail!(
            "Invalid font header magic bytes {:02X?}: not a valid font file ({:?})",
            header,
            path
        );
    }

    Ok(())
}

/// Sanitize destination filename to prevent directory traversal and verify font extension.
pub fn sanitize_filename(filename: &str) -> Result<String> {
    let name = filename.trim();
    if name.is_empty() {
        bail!("Empty filename specified in manifest");
    }
    if name.contains('/') || name.contains('\\') || name.contains("..") || name.contains('\0') {
        bail!(
            "Potentially malicious filename containing directory separators or traversal: {}",
            name
        );
    }

    let lower = name.to_lowercase();
    let valid_ext = lower.ends_with(".ttf")
        || lower.ends_with(".otf")
        || lower.ends_with(".ttc")
        || lower.ends_with(".woff")
        || lower.ends_with(".woff2");

    if !valid_ext {
        bail!(
            "Invalid font file extension for filename: {} (expected .ttf, .otf, .ttc, .woff, .woff2)",
            name
        );
    }

    Ok(name.to_string())
}

/// Validate destination path to ensure it resides within the allowed target directory and has a valid font filename.
pub fn validate_destination_path(dest_path: &Path, target_dir: Option<&Path>) -> Result<()> {
    let filename = dest_path
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| anyhow::anyhow!("Destination path missing filename: {:?}", dest_path))?;

    sanitize_filename(filename)?;

    for comp in dest_path.components() {
        if let std::path::Component::ParentDir = comp {
            bail!(
                "Path traversal component ('..') detected in destination path: {:?}",
                dest_path
            );
        }
    }

    if let Ok(meta) = dest_path.symlink_metadata() {
        if meta.file_type().is_symlink() {
            bail!("Destination path {:?} is a symlink", dest_path);
        }
    }

    if let Some(target) = target_dir {
        let canonical_target = target
            .canonicalize()
            .unwrap_or_else(|_| target.to_path_buf());

        let canonical_dest = if dest_path.exists() {
            dest_path
                .canonicalize()
                .unwrap_or_else(|_| dest_path.to_path_buf())
        } else if let Some(parent) = dest_path.parent() {
            if parent.exists() {
                parent
                    .canonicalize()
                    .map(|p| p.join(filename))
                    .unwrap_or_else(|_| dest_path.to_path_buf())
            } else {
                dest_path.to_path_buf()
            }
        } else {
            dest_path.to_path_buf()
        };

        if !canonical_dest.starts_with(&canonical_target) && !dest_path.starts_with(target) {
            bail!(
                "Destination path {:?} is not confined to authorized target directory {:?}",
                dest_path,
                target
            );
        }
    }

    Ok(())
}

/// Parse and validate a Manifest from a JSON string or file reader.
pub fn parse_and_validate_manifest(content: &str) -> Result<Manifest> {
    let manifest: Manifest = serde_json::from_str(content)
        .with_context(|| "Failed to parse JSON manifest schema")?;

    if manifest.fonts.is_empty() {
        bail!("Manifest contains no font entries");
    }

    for font in &manifest.fonts {
        if font.family_name.trim().is_empty() {
            bail!("Manifest contains font entry with empty family_name");
        }
        if font.files.is_empty() {
            bail!(
                "Font '{}' contains no files to process",
                font.family_name
            );
        }

        for file_entry in &font.files {
            match manifest.action {
                ManifestAction::Install => {
                    let source = file_entry.source_path.as_ref().ok_or_else(|| {
                        anyhow::anyhow!(
                            "Missing source_path for font '{}' in install manifest",
                            font.family_name
                        )
                    })?;

                    if !source.exists() || !source.is_file() {
                        bail!("Source font file does not exist: {:?}", source);
                    }

                    verify_font_magic_bytes(source)?;

                    if let Some(dest_name) = &file_entry.destination_filename {
                        sanitize_filename(dest_name)?;
                    }

                    if let Some(dest_path) = &file_entry.destination_path {
                        validate_destination_path(dest_path, manifest.target_dir.as_deref())?;
                    }
                }
                ManifestAction::Uninstall => {
                    if file_entry.destination_filename.is_none()
                        && file_entry.destination_path.is_none()
                    {
                        bail!(
                            "Uninstall file entry for '{}' must specify destination_filename or destination_path",
                            font.family_name
                        );
                    }
                    if let Some(dest_name) = &file_entry.destination_filename {
                        sanitize_filename(dest_name)?;
                    }
                    if let Some(dest_path) = &file_entry.destination_path {
                        validate_destination_path(dest_path, manifest.target_dir.as_deref())?;
                    }
                }
            }
        }
    }

    Ok(manifest)
}
