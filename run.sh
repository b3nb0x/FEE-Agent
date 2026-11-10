#!/bin/sh
# FEE-Agent starten – eigenständiger Agent mit Web-GUI
# GUI: http://localhost:8765   |   Endpoint-Modell: in der GUI einstellen
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
    python3 -m venv .venv
    ./.venv/bin/pip install -q -r requirements.txt
fi
exec ./.venv/bin/python -m feeagent.server
