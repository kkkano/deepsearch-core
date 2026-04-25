#!/usr/bin/env bash
# 一键把 deepsearch-core 注册到 Claude Code MCP 配置。
#
# 用法：
#   bash scripts/install_mcp.sh

set -euo pipefail

if ! command -v claude >/dev/null 2>&1; then
    echo "❌ 'claude' CLI not found. Install Claude Code first:"
    echo "   https://docs.claude.com/claude-code"
    exit 1
fi

if ! python -c "import deepsearch_core" 2>/dev/null; then
    echo "📦 Installing deepsearch-core..."
    pip install -e "$(dirname "$0")/.."
fi

echo "🔌 Registering deepsearch MCP server..."
claude mcp add deepsearch -- python -m deepsearch_core.adapters.mcp

echo "✅ Done! Restart Claude Code, then say 'use deepsearch to research ...'"
