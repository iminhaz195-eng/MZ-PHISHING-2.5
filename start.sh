#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#   FILE: start.sh  —  launcher (gunicorn + telegram bot + tunnel)
# ═══════════════════════════════════════════════════════════════════
set -e

cd "$(dirname "$0")"

if [ -d "myenv" ]; then source myenv/bin/activate; fi
if [ -d "venv" ]; then source venv/bin/activate; fi

FLASK_PORT="${FLASK_PORT:-8080}"
WORKERS="${WORKERS:-1}"
THREADS="${THREADS:-32}"

echo "[*] Stopping old processes..."
pkill -f "gunicorn wsgi:application" 2>/dev/null || true
pkill -f "python main.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2

echo "[*] Starting gunicorn on :$FLASK_PORT ($WORKERS workers x $THREADS threads)"
gunicorn wsgi:application \
    --bind "0.0.0.0:$FLASK_PORT" \
    --worker-class gthread \
    --workers "$WORKERS" \
    --threads "$THREADS" \
    --timeout 60 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --access-logfile "-" \
    --error-logfile "-" \
    --log-level info \
    --daemon \
    --pid /tmp/mzbot_gunicorn.pid

sleep 3

if ! python3 -c "import socket; socket.create_connection(('127.0.0.1', $FLASK_PORT), timeout=3)" 2>/dev/null; then
    echo "[!] gunicorn NOT responding on port $FLASK_PORT"
    exit 1
fi

echo "[✓] gunicorn ready on port $FLASK_PORT"

echo "[*] Starting Telegram bot + cloudflared..."
export SKIP_FLASK=1
export FLASK_PORT="$FLASK_PORT"
python main.py