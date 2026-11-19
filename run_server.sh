#!/usr/bin/env bash
# run_server.sh — Linux/macOS convenience script to start the file-transfer server.
# Usage:  chmod +x run_server.sh && ./run_server.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================================"
echo "  Multi-Threaded File Transfer Server — Starting..."
echo "============================================================"
echo ""

cd "$SCRIPT_DIR/server"
python3 server.py
