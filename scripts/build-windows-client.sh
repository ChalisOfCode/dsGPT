#!/usr/bin/env bash
# Portable cross-build; pass the LLVM-MinGW bin directory as argument 1.
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$1:$PATH"
export CARGO_TARGET_X86_64_PC_WINDOWS_GNULLVM_LINKER=x86_64-w64-mingw32-clang
export CC_x86_64_pc_windows_gnullvm=x86_64-w64-mingw32-clang
npm --prefix "$repo_root/clients/desktop" ci
npm --prefix "$repo_root/clients/desktop" run build
cargo build --manifest-path "$repo_root/clients/desktop/src-tauri/Cargo.toml" --locked --release --features custom-protocol --target x86_64-pc-windows-gnullvm
