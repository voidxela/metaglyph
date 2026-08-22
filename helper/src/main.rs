//! Main CLI entry point for metaglyph-helper.

mod font_cache;
mod installer;
mod manifest;

use std::env;
use std::fs;
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::process::exit;

use font_cache::refresh_font_cache;
use installer::{execute_install, execute_uninstall};
use manifest::{parse_and_validate_manifest, HelperResult, ManifestAction};

const VERSION: &str = env!("CARGO_PKG_VERSION");

fn print_usage() {
    eprintln!(
        r#"metaglyph-helper v{}
Privilege escalation helper for Metaglyph OS font management

USAGE:
    metaglyph-helper --manifest <PATH>
    metaglyph-helper -m <PATH>
    metaglyph-helper --help
    metaglyph-helper --version

OPTIONS:
    -m, --manifest <PATH>    Path to the JSON install manifest file (or '-' for stdin)
    -h, --help               Print help information
    -V, --version            Print version information
"#,
        VERSION
    );
}

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() < 2 {
        print_usage();
        let result = HelperResult::failure(
            "unknown",
            vec!["Missing required --manifest argument".to_string()],
            "Invalid command-line invocation".to_string(),
        );
        println!("{}", serde_json::to_string_pretty(&result).unwrap());
        exit(1);
    }

    let mut manifest_path: Option<String> = None;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "-h" | "--help" => {
                print_usage();
                exit(0);
            }
            "-V" | "--version" => {
                println!("metaglyph-helper {}", VERSION);
                exit(0);
            }
            "-m" | "--manifest" => {
                if i + 1 < args.len() {
                    manifest_path = Some(args[i + 1].clone());
                    i += 1;
                } else {
                    eprintln!("Error: --manifest requires a path argument");
                    exit(1);
                }
            }
            arg if arg.starts_with("--manifest=") => {
                manifest_path = Some(arg.trim_start_matches("--manifest=").to_string());
            }
            _ => {}
        }
        i += 1;
    }

    let path_str = match manifest_path {
        Some(p) => p,
        None => {
            print_usage();
            let result = HelperResult::failure(
                "unknown",
                vec!["No manifest path supplied".to_string()],
                "Missing --manifest argument".to_string(),
            );
            println!("{}", serde_json::to_string_pretty(&result).unwrap());
            exit(1);
        }
    };

    // Read manifest JSON content
    let content = if path_str == "-" {
        let mut buffer = String::new();
        if let Err(e) = io::stdin().read_to_string(&mut buffer) {
            let result = HelperResult::failure(
                "unknown",
                vec![format!("Failed to read manifest from stdin: {}", e)],
                "Stdin read error".to_string(),
            );
            println!("{}", serde_json::to_string_pretty(&result).unwrap());
            exit(1);
        }
        buffer
    } else {
        match fs::read_to_string(&path_str) {
            Ok(c) => c,
            Err(e) => {
                let result = HelperResult::failure(
                    "unknown",
                    vec![format!("Failed to read manifest file {:?}: {}", path_str, e)],
                    "Manifest read error".to_string(),
                );
                println!("{}", serde_json::to_string_pretty(&result).unwrap());
                exit(1);
            }
        }
    };

    // Parse and validate manifest
    let manifest = match parse_and_validate_manifest(&content) {
        Ok(m) => m,
        Err(e) => {
            let result = HelperResult::failure(
                "validate",
                vec![format!("Manifest validation error: {:#}", e)],
                "Validation failed".to_string(),
            );
            println!("{}", serde_json::to_string_pretty(&result).unwrap());
            exit(1);
        }
    };

    let target_dir_ref = manifest.target_dir.as_deref();

    // Execute action
    match manifest.action {
        ManifestAction::Install => match execute_install(&manifest) {
            Ok(installed) => {
                let _ = refresh_font_cache(target_dir_ref);
                let count = installed.len();
                let result = HelperResult::success(
                    "install",
                    installed,
                    Vec::new(),
                    format!("Successfully installed {} font file(s)", count),
                );
                println!("{}", serde_json::to_string_pretty(&result).unwrap());
                exit(0);
            }
            Err(e) => {
                let result = HelperResult::failure(
                    "install",
                    vec![format!("Installation failed: {:#}", e)],
                    "Installation error".to_string(),
                );
                println!("{}", serde_json::to_string_pretty(&result).unwrap());
                exit(1);
            }
        },
        ManifestAction::Uninstall => match execute_uninstall(&manifest) {
            Ok(uninstalled) => {
                let _ = refresh_font_cache(target_dir_ref);
                let count = uninstalled.len();
                let result = HelperResult::success(
                    "uninstall",
                    Vec::new(),
                    uninstalled,
                    format!("Successfully uninstalled {} font file(s)", count),
                );
                println!("{}", serde_json::to_string_pretty(&result).unwrap());
                exit(0);
            }
            Err(e) => {
                let result = HelperResult::failure(
                    "uninstall",
                    vec![format!("Uninstallation failed: {:#}", e)],
                    "Uninstallation error".to_string(),
                );
                println!("{}", serde_json::to_string_pretty(&result).unwrap());
                exit(1);
            }
        },
    }
}
