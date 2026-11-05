#!/usr/bin/env bash
# SeiMLAI GUI Launcher
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Finder does not load the user's interactive shell, so conda may not be in PATH.
CONDA_EXE="$(command -v conda || true)"
if [[ -z "$CONDA_EXE" ]]; then
    for candidate in \
        "$HOME/miniconda3/bin/conda" \
        "$HOME/anaconda3/bin/conda" \
        "$HOME/opt/miniconda3/bin/conda" \
        "/opt/homebrew/Caskroom/miniconda/base/bin/conda" \
        "/opt/homebrew/anaconda3/bin/conda"; do
        if [[ -x "$candidate" ]]; then
            CONDA_EXE="$candidate"
            break
        fi
    done
fi

if [[ -n "$CONDA_EXE" ]]; then
    eval "$("$CONDA_EXE" shell.bash hook)"
    if ! conda env list | awk '{print $1}' | grep -qx catalog; then
        echo "[SeiMLAI] Creating conda environment 'catalog'..."
        conda create -y -n catalog python=3.11 pip
        conda run -n catalog python -m pip install -e .
        conda run -n catalog python -m pip install nicegui watchdog
    fi
    conda activate catalog
fi

exec python main.py --gui "$@"

