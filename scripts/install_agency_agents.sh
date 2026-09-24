#!/usr/bin/env bash
# Script to install Agency Agents from msitarzewski/agency-agents repo
set -euo pipefail

REPO_URL="https://github.com/msitarzewski/agency-agents.git"
CLONE_DIR="/tmp/agency-agents"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[+] Cloning msitarzewski/agency-agents..."
if [ -d "$CLONE_DIR" ]; then
	rm -rf "$CLONE_DIR"
fi

git clone "$REPO_URL" "$CLONE_DIR"

echo "[+] Installing Agency Agents for Claude Code and Codex..."
CLAUDE_CONFIG_DIR="$ROOT_DIR/.claude" \
	CODEX_AGENTS_DIR="$ROOT_DIR/.codex/agents" \
	"$CLONE_DIR/scripts/install.sh" --tool claude-code,codex --no-interactive

echo "[+] Agency Agents successfully installed into $ROOT_DIR/.claude/agents and $ROOT_DIR/.codex/agents"
