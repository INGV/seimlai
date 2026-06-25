from __future__ import annotations

import sys
from pathlib import Path


def add_repo_root_to_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def build_cli_context(config_path: str = "config.yaml"):
    add_repo_root_to_path()
    from seismic_workflow.context import build_context, ensure_initial_directories

    ctx = build_context(config_path)
    ensure_initial_directories(ctx)
    return ctx
