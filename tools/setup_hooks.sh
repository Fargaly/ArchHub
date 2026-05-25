#!/usr/bin/env bash
# setup_hooks.sh - one-time per-clone hook activation (bash variant).
# See tools/setup_hooks.ps1 for the Windows-native version.
#
# Usage:
#   bash tools/setup_hooks.sh

set -euo pipefail

if [[ ! -d .git ]]; then
    echo "setup_hooks: no .git in current directory (cwd=$(pwd))" >&2
    exit 2
fi

current=$(git config --get core.hooksPath 2>/dev/null || true)
if [[ "$current" == ".githooks" ]]; then
    echo "OK core.hooksPath already pointing at .githooks"
else
    git config core.hooksPath .githooks
    echo "Set core.hooksPath = .githooks (was: '$current')"
fi

for hook in pre-commit pre-push; do
    p=".githooks/$hook"
    if [[ ! -f "$p" ]]; then
        echo "WARN: $p MISSING" >&2
    else
        chmod +x "$p" 2>/dev/null || true
        echo "  - $p present"
    fi
done

# Run tripwire to surface current state.
if command -v powershell >/dev/null 2>&1; then
    powershell -NoProfile -ExecutionPolicy Bypass -File tools/cs_tripwire.ps1
fi
