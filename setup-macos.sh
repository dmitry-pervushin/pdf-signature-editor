#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew est requis. Installez-le depuis https://brew.sh"
  exit 1
fi

echo "Installation de Python, Tk et Poppler…"
brew install python@3.13 python-tk@3.13 poppler

PYTHON_BIN="$(brew --prefix)/bin/python3.13"
"$PYTHON_BIN" -m venv "$SCRIPT_DIR/.venv"
"$SCRIPT_DIR/.venv/bin/python" -m pip install --upgrade pip
"$SCRIPT_DIR/.venv/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"

echo
echo "Installation terminée."
echo "Lancez l’application avec : $SCRIPT_DIR/start-macos.command"
