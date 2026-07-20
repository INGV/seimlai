#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Absolute location stage.

Run HypoEllipse through the INGV Docker image and write the output expected by
downstream steps.
"""

from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

DOCKER_IMAGE = None
FILECOM_NAME = "filecom"
PHS_NAME = "out_conv.phs"
STATIONS_NAME = "all.he"
MODEL_NAME = "grad.mod"
PARAMETERS_NAME = "improved.cfg"
PRINTER_OUTPUT_NAME = "location-1D.out"
DOCKER_START_TIMEOUT_SECONDS = None
HYPOELLIPSE_CONFIGURATION_DIR = Path(__file__).resolve().parent.parent / "user_configuration" / "hypoellipse"


def _apply_context(ctx):
    globals().update(ctx.legacy_globals())
    globals().update({
        "DOCKER_IMAGE": HYPOELLIPSE_DOCKER_IMAGE,
        "DOCKER_START_TIMEOUT_SECONDS": HYPOELLIPSE_DOCKER_START_TIMEOUT_SECONDS,
    })


def _require_file(path, label):
    if not path.exists():
        print(f"ERROR: {label} not found: {path}")
        sys.exit(1)


def _write_filecom(path):
    path.write_text(
        "\n".join([
            "stdin",
            "y",
            "output",
            "stdout",
            f"../output/{PRINTER_OUTPUT_NAME}",
            "y",
            "../output/output.sum",
            "y",
            "../output/output.arc",
            "n",
            "n",
            f"jump {PARAMETERS_NAME}",
            f"jump {MODEL_NAME}",
            "begin station list +1 19800101",
            f"jump {STATIONS_NAME}",
            "arrival times next",
            f"jump {PHS_NAME}",
            "",
        ]),
        encoding="utf-8",
    )


def _enable_printer_output(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text(
        "\n".join(
            "printer option     1" if line.strip().startswith("printer option") else line
            for line in lines
        ) + "\n",
        encoding="utf-8",
    )


def _prepare_run_dir(ctx):
    run_dir = Path(ctx.paths.hypoellipse_dir)
    input_dir = Path(ctx.paths.hypoellipse_input_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    Path(ctx.paths.hypoellipse_output_dir).mkdir(parents=True, exist_ok=True)

    phs_path = input_dir / PHS_NAME
    stations_path = input_dir / STATIONS_NAME
    model_path = HYPOELLIPSE_CONFIGURATION_DIR / MODEL_NAME
    parameters_path = HYPOELLIPSE_CONFIGURATION_DIR / PARAMETERS_NAME

    _require_file(phs_path, "HypoEllipse phases file")
    _require_file(stations_path, "HypoEllipse stations file")
    _require_file(model_path, "HypoEllipse velocity model")
    _require_file(parameters_path, "HypoEllipse parameter file")

    shutil.copy2(model_path, input_dir / MODEL_NAME)
    shutil.copy2(parameters_path, input_dir / PARAMETERS_NAME)
    _enable_printer_output(input_dir / PARAMETERS_NAME)
    _write_filecom(input_dir / FILECOM_NAME)
    return run_dir


def _docker_is_ready():
    return subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _ensure_docker_ready():
    if _docker_is_ready():
        return

    if platform.system() == "Darwin":
        print("Docker is not ready. Opening Docker Desktop...")
        subprocess.run(["open", "-a", "Docker"], check=False)
        deadline = time.time() + DOCKER_START_TIMEOUT_SECONDS
        while time.time() < deadline:
            if _docker_is_ready():
                return
            time.sleep(3)

    print("ERROR: Docker is not running or is not reachable.")
    print("Start Docker Desktop and rerun this step.")
    sys.exit(1)

def run(ctx):
    _apply_context(ctx)
    run_dir = _prepare_run_dir(ctx)
    location_1d_out_path = Path(ctx.paths.location_1d_out_path)
    location_1d_out_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_path = location_1d_out_path.parent / "hypoellipse.stdout"
    stderr_path = location_1d_out_path.parent / "hypoellipse.stderr"
    _ensure_docker_ready()

    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{run_dir.resolve()}:/opt/data",
        DOCKER_IMAGE,
        FILECOM_NAME,
    ]

    print(f"Running HypoEllipse in Docker: {DOCKER_IMAGE}")
    print(f"Run directory: {run_dir}")
    with stdout_path.open("w", encoding="utf-8") as stdout_file:
        result = subprocess.run(
            command,
            stdout=stdout_file,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )

    stderr_path.write_text(result.stderr or "", encoding="utf-8")
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        print(f"ERROR: HypoEllipse failed with exit code {result.returncode}")
        sys.exit(1)

    if not location_1d_out_path.exists() or location_1d_out_path.stat().st_size == 0:
        print(f"ERROR: HypoEllipse produced no printer output: {location_1d_out_path}")
        sys.exit(1)

    print(f"HypoEllipse output written to: {location_1d_out_path}")


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_hypoellipse_check = run


if __name__ == "__main__":
    main()
