#!/usr/bin/env bash
# Incrementally re-index vault notes changed since last run.
# Called by the Stop hook after each session.
set -euo pipefail

VAULT="${OBSIDIAN_VAULT_PATH:-/Users/guido.dilauro/WORKDIR/WORK-WIKI}"
DB="$HOME/.claude/vault-index.db"
SCRIPT="$HOME/.claude/build_vault_index.py"

exec python3 "$SCRIPT" --vault "$VAULT" --db "$DB" --incremental >> "$HOME/.claude/vault-index.log" 2>&1
