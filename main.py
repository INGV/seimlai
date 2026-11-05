#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")


def _ensure_catalog_env():
    """Ensure the workflow runs inside the conda environment containing obspy, torch, etc."""
    try:
        import obspy  # noqa: F401
        return
    except ImportError:
        pass

    if os.environ.get("_SEIMLAI_ENV_SWITCHED") == "1":
        return

    import shutil
    import subprocess
    from pathlib import Path

    target_py = None
    conda_exe = shutil.which("conda")
    if conda_exe:
        try:
            res = subprocess.run([conda_exe, "info", "--envs"], capture_output=True, text=True, timeout=5)
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0] in ("catalog", "seismic-workflow"):
                    candidate = Path(parts[-1]) / "bin" / "python"
                    if candidate.exists():
                        target_py = str(candidate)
                        break
        except Exception:
            pass

    if not target_py:
        candidates = [
            Path("/opt/homebrew/Caskroom/miniconda/base/envs/catalog/bin/python"),
            Path(sys.prefix).parent / "catalog" / "bin" / "python",
            Path.home() / "miniconda3" / "envs" / "catalog" / "bin" / "python",
            Path.home() / "opt" / "miniconda3" / "envs" / "catalog" / "bin" / "python",
            Path.home() / ".conda" / "envs" / "catalog" / "bin" / "python",
        ]
        for c in candidates:
            if c.exists():
                target_py = str(c)
                break

    if target_py and target_py != sys.executable:
        print(f"[SeiMLAI] Automatically activating 'catalog' conda environment...")
        print(f"         Interpreter: {target_py}\n")
        new_env = os.environ.copy()
        new_env["_SEIMLAI_ENV_SWITCHED"] = "1"
        os.execve(target_py, [target_py] + sys.argv, new_env)


_ensure_catalog_env()

from seimlai.main import main


if __name__ == "__main__":
    main()
