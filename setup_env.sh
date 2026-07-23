#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

if [ -d "$VENV_DIR" ]; then
    echo ".venv already exists at $VENV_DIR"
    exit 0
fi

echo "Creating .venv ..."
python -m venv "$VENV_DIR"

# Activate: .venv/Scripts/activate on Git Bash/Windows, .venv/bin/activate on Unix
if [ -f "$VENV_DIR/Scripts/activate" ]; then
    source "$VENV_DIR/Scripts/activate"
else
    source "$VENV_DIR/bin/activate"
fi

python -m pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt"
echo "Done. Environment ready at $VENV_DIR"
