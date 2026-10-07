#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#   start.sh — bulletproof supervisor (no 502, auto-restart)
# ═══════════════════════════════════════════════════════════════════
cd "$(dirname "$0")"

if [ -d "myenv" ]; then source myenv/bin/activate; fi
if [ -d "venv" ]; then source venv/bin/activate; fi

FLASK_PORT="${FLASK_PORT:-8080}"
WORKERS="${WORKERS:-1}"
THREADS="${THREADS:-32}"
CHECK_INTERVAL=10

# ─── cleanup on exit ───
cleanup() {
    echo "[*] Shutting down supervisor..."
    pkill -f "gunicorn wsgi:application" 2>/dev/null || true
    pkill -f "python main.py" 2>/dev/null || true
    pkill -f "cloudflared tunnel" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM EXIT

# ─── kill old ───
echo "[*] Killing old processes..."
pkill -f "gunicorn wsgi:application" 2>/dev/null || true
pkill -f "python main.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2

# ─── start gunicorn ───
start_gunicorn() {
    echo "[*] Starting gunicorn on :$FLASK_PORT"
    gunicorn wsgi:application \
        --bind "0.0.0.0:$FLASK_PORT" \
        --worker-class gthread \
        --workers "$WORKERS" \
        --threads "$THREADS" \
        --timeout 60 --graceful-timeout 30 --keep-alive 5 \
        --access-logfile "-" --error-logfile "-" \
        --log-level info &
    GUNICORN_PID=$!
    echo "[✓] gunicorn PID $GUNICORN_PID"
}

# ─── start bot ───
start_bot() {
    echo "[*] Starting telegram bot..."
    export SKIP_FLASK=1
    export FLASK_PORT="$FLASK_PORT"
    python main.py &
    BOT_PID=$!
    echo "[✓] bot PID $BOT_PID"
}

# ─── initial start ───
start_gunicorn
sleep 4

if ! python3 -c "import socket; socket.create_connection(('127.0.0.1', $FLASK_PORT), timeout=3)" 2>/dev/null; then
    echo "[!] gunicorn failed to bind. Exiting."
    exit 1
fi
echo "[✓] Flask ready on :$FLASK_PORT"

start_bot
sleep 5

echo ""
echo "════════════════════════════════════════════════════"
echo "  SUPERVISOR RUNNING"
echo "  Flask PID : $GUNICORN_PID"
echo "  Bot PID   : $BOT_PID"
echo "  Watching every ${CHECK_INTERVAL}s..."
echo "════════════════════════════════════════════════════"
echo ""

# ─── watchdog loop ───
while true; do
    sleep "$CHECK_INTERVAL"

    # check gunicorn
    if ! kill -0 $GUNICORN_PID 2>/dev/null; then
        echo "[!] $(date '+%H:%M:%S') gunicorn died — restarting..."
        pkill -f "gunicorn wsgi:application" 2>/dev/null || true
        sleep 1
        start_gunicorn
    fi

    # check flask port
    if ! python3 -c "import socket; socket.create_connection(('127.0.0.1', $FLASK_PORT), timeout=2)" 2>/dev/null; then
        echo "[!] $(date '+%H:%M:%S') port $FLASK_PORT dead — restarting gunicorn..."
        pkill -f "gunicorn wsgi:application" 2>/dev/null || true
        sleep 1
        start_gunicorn
    fi

    # check bot
    if ! kill -0 $BOT_PID 2>/dev/null; then
        echo "[!] $(date '+%H:%M:%S') bot died — restarting..."
        pkill -f "python main.py" 2>/dev/null || true
        pkill -f "cloudflared tunnel" 2>/dev/null || true
        sleep 2
        start_bot
    fi
done
