#!/bin/bash
# ═══════════════════════════════════════════════════════════════════
#   FILE: stop.sh  —  stop everything
# ═══════════════════════════════════════════════════════════════════
pkill -f "gunicorn wsgi:application" 2>/dev/null || true
pkill -f "python main.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
rm -f /tmp/mzbot_gunicorn.pid
echo "[✓] Stopped."