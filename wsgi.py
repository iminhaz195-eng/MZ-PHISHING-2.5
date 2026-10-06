# ═══════════════════════════════════════════════════════════════════
#   FILE: wsgi.py  —  gunicorn entrypoint
# ═══════════════════════════════════════════════════════════════════
import os
import sys

os.environ["SKIP_FLASK"] = "1"
os.environ["SKIP_SIGNAL_HANDLERS"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import flask_app

application = flask_app