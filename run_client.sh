#!/usr/bin/env bash
# run_client.sh — Linux/macOS convenience script to start the file-transfer client.
# Open a NEW terminal for each client instance you want to run concurrently.
# Usage:  chmod +x run_client.sh && ./run_client.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================================"
echo "  Multi-Threaded File Transfer Client — Starting..."
echo "============================================================"
echo ""

cd "$SCRIPT_DIR/client"
python3 client.py
