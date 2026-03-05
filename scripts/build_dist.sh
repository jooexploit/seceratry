#!/usr/bin/env bash
set -euo pipefail

python3 -m pip install --upgrade pip
python3 -m pip install pyinstaller
pyinstaller --noconfirm --onefile --name personal_assistant personal_assistant.py
