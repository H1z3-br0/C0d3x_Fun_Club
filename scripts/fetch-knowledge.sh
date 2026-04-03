#!/usr/bin/env bash
set -euo pipefail

KNOWLEDGE_DIR="${1:-$(dirname "$0")/../knowledge}"
mkdir -p "$KNOWLEDGE_DIR"

clone_or_pull() {
    local repo="$1" dir="$2"
    if [ -d "$dir/.git" ]; then
        echo "Updating $dir ..."
        git -C "$dir" pull --ff-only --depth=1 2>/dev/null || git -C "$dir" fetch --depth=1 && git -C "$dir" reset --hard origin/HEAD
    else
        echo "Cloning $repo -> $dir ..."
        git clone --depth=1 "$repo" "$dir"
    fi
}

clone_or_pull "https://github.com/HackTricks-wiki/hacktricks"         "$KNOWLEDGE_DIR/hacktricks"
clone_or_pull "https://github.com/swisskyrepo/PayloadsAllTheThings"    "$KNOWLEDGE_DIR/PayloadsAllTheThings"

echo ""
echo "Knowledge base ready at: $KNOWLEDGE_DIR"
du -sh "$KNOWLEDGE_DIR"/* 2>/dev/null
