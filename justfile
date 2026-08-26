# Metaglyph Project Justfile
# https://github.com/casey/just

set shell := ["bash", "-uc"]

python_bin := if path_exists(".venv/bin/python") == "true" { ".venv/bin/python" } else { "python3" }
pytest_bin := if path_exists(".venv/bin/pytest") == "true" { ".venv/bin/pytest" } else { "pytest" }

# Default recipe lists available actions
default:
    @just --list

# Run application tests and linting
test-app:
    QT_QPA_PLATFORM=offscreen {{pytest_bin}} -v -m "not visual"

# Run helper cargo tests and linting
test-helper:
    @if command -v cargo >/dev/null 2>&1; then \
        cargo check --manifest-path helper/Cargo.toml --all-targets; \
        cargo test --manifest-path helper/Cargo.toml --verbose; \
        cargo clippy --manifest-path helper/Cargo.toml -- -D warnings; \
    else \
        echo -e "\033[1;33m[WARNING] cargo not found. Skipping helper tests and clippy.\033[0m" >&2; \
    fi

# Run all tests and linting (app and helper)
test: test-app test-helper

# Build the standalone Rust privilege escalation helper binary
build-helper:
    @if command -v cargo >/dev/null 2>&1; then \
        cargo build --release --manifest-path helper/Cargo.toml; \
    else \
        echo -e "\033[1;33m[WARNING] cargo not found. Skipping helper compilation.\033[0m" >&2; \
    fi

# Start Metaglyph from source, warning if helper binary is missing
run *args:
    @if [ ! -f "helper/target/release/metaglyph-helper" ] && [ ! -f "helper/target/release/metaglyph-helper.exe" ] && [ ! -f "helper/target/debug/metaglyph-helper" ] && [ ! -f "helper/target/debug/metaglyph-helper.exe" ] && [ ! -f "bin/metaglyph-helper" ] && ! command -v metaglyph-helper >/dev/null 2>&1; then \
        echo -e "\033[1;33m[WARNING] metaglyph-helper binary not found in helper targets or PATH. System-wide font operations will be disabled. Run \`just build-helper\` to compile it.\033[0m" >&2; \
    fi
    {{python_bin}} -m metaglyph {{args}}

# Build helper binary and generate Linux AppImage package
package-linux: build-helper
    bash scripts/package_linux.sh
