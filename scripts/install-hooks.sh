#!/usr/bin/env bash
# Install git hooks tracked under scripts/hooks/ into .git/hooks/.
#
# Idempotent: overwrites hook files we ship and leaves other hooks
# alone. Safe to re-run after updating a hook.

set -e

repo_root="$(git rev-parse --show-toplevel)"
src_dir="$repo_root/scripts/hooks"
dst_dir="$repo_root/.git/hooks"

if [ ! -d "$src_dir" ]; then
    echo "No hooks to install (missing $src_dir)" >&2
    exit 0
fi

mkdir -p "$dst_dir"

installed=0
for hook in "$src_dir"/*; do
    [ -f "$hook" ] || continue
    name="$(basename "$hook")"
    dst="$dst_dir/$name"
    cp "$hook" "$dst"
    chmod +x "$dst"
    echo "Installed: .git/hooks/$name"
    installed=$((installed + 1))
done

if [ "$installed" -eq 0 ]; then
    echo "No hook files found under $src_dir" >&2
fi
