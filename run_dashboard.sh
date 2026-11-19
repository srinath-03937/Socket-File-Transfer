#!/usr/bin/env bash
# run_dashboard.sh — Launch the web dashboard (Linux/macOS)
# Usage: chmod +x run_dashboard.sh && ./run_dashboard.sh
# Then open  http://127.0.0.1:8080  in your browser.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "============================================================"
echo "  Socket File Transfer — Web Dashboard"
echo "  Opening at http://127.0.0.1:8080"
echo "============================================================"
echo ""

# Try to auto-open the browser.
(sleep 2 && xdg-open http://127.0.0.1:8080 2>/dev/null || open http://127.0.0.1:8080 2>/dev/null) &

cd "$SCRIPT_DIR"
python3 dashboard/app.py
