#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#   start.sh — SINGLE PROCESS (bot + flask together)
#   No gunicorn, no 404, no 502, no state sharing issues
# ═══════════════════════════════════════════════════════════════════
cd "$(dirname "$0")"

if [ -d "myenv" ]; then source myenv/bin/activate; fi
if [ -d "venv" ]; then source venv/bin/activate; fi

echo "[*] Cleaning old processes..."
pkill -f "gunicorn wsgi:application" 2>/dev/null || true
pkill -f "python main.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2

echo "[*] Starting supervisor loop..."
while true; do
    echo ""
    echo "════════════════════════════════════════════════════"
    echo "[$(date)] Starting bot (single process mode)"
    echo "════════════════════════════════════════════════════"
    
    # unset SKIP_FLASK so main.py starts Flask internally
    unset SKIP_FLASK
    python main.py
    RC=$?
    
    echo ""
    echo "[$(date)] Bot exited (rc=$RC) — restarting in 5s..."
    pkill -f "cloudflared tunnel" 2>/dev/null || true
    sleep 5
done
