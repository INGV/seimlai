#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Absolute location stage.

Run HypoEllipse through the INGV Docker image and write the output expected by
downstream steps.
"""

from pathlib import Path
import csv
import platform
import shutil
import subprocess
import sys
import time
import re

DOCKER_IMAGE = None
FILECOM_NAME = "filecom"
PHS_NAME = "out_conv.phs"
STATIONS_NAME = "all.he"
#alias for 5 stations characters
ALIAS_PHS_NAME = "out_conv.alias.phs"
ALIAS_STATIONS_NAME = "all.alias.he"
ALIAS_MAP_NAME = "station_aliases.csv"

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


def _write_filecom(path, stations_name, phs_name):
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
            f"jump {stations_name}",
            "arrival times next",
            f"jump {phs_name}",
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

def _replace_fixed_width(line, start, end, value):
    """Replace a fixed-width field without changing the source file."""
    has_newline = line.endswith("\n")
    text = line[:-1] if has_newline else line
    text = text.ljust(end)
    text = text[:start] + value + text[end:]
    return text + ("\n" if has_newline else "")


def _station_code_from_he_line(line):
    """
    all.he:
    - characters 1–4: station base code
    - character 80: fifth character, if present
    """
    base = line[:4].strip()
    if not base:
        return None

    suffix = line[79:80].strip() if len(line) >= 80 else ""
    return base + suffix


def _station_code_from_phs_line(line):
    """
    out_conv.phs:
    - characters 1–4: station base code
    - character 78: fifth character, if present
    """
    base = line[:4].strip()
    if not base:
        return None

    suffix = line[77:78].strip() if len(line) >= 78 else ""
    return base + suffix


def _create_alias_inputs(stations_path, phs_path, alias_stations_path,
                         alias_phs_path, alias_map_path):
    """
    Create temporary four-character station aliases for Hypoellipse.
    Original all.he and out_conv.phs are read-only and never overwritten.
    """
    with stations_path.open("r", encoding="utf-8") as f_in:
        station_lines = f_in.readlines()

    station_codes = {
        code for line in station_lines
        if (code := _station_code_from_he_line(line)) is not None
    }

    if not station_codes:
        raise RuntimeError(f"No stations found in {stations_path}")

    if len(station_codes) > 999:
        raise RuntimeError(
            "This alias convention supports at most 999 stations."
        )

    # Stable aliases: same real station always receives the same alias.
    aliases = {
        station: f"S{index:03d}"
        for index, station in enumerate(sorted(station_codes), start=1)
    }

    with phs_path.open("r", encoding="utf-8") as f_in:
        phs_lines = f_in.readlines()

    phase_codes = {
        code for line in phs_lines
        if (code := _station_code_from_phs_line(line)) is not None
    }

    missing_stations = sorted(phase_codes - station_codes)
    if missing_stations:
        raise RuntimeError(
            "Stations used by out_conv.phs but absent from all.he: "
            + ", ".join(missing_stations[:20])
        )

    # Temporary station file: alias in columns 1–4; blank fifth-code column.
    with alias_stations_path.open("w", encoding="utf-8") as f_out:
        for line in station_lines:
            code = _station_code_from_he_line(line)
            if code is None:
                f_out.write(line)
                continue

            alias_line = _replace_fixed_width(line, 0, 4, aliases[code])
            alias_line = _replace_fixed_width(alias_line, 79, 80, " ")
            f_out.write(alias_line)

    # Temporary phase file: alias in columns 1–4; blank fifth-code column.
    with alias_phs_path.open("w", encoding="utf-8") as f_out:
        for line in phs_lines:
            code = _station_code_from_phs_line(line)
            if code is None:
                f_out.write(line)
                continue

            alias_line = _replace_fixed_width(line, 0, 4, aliases[code])
            alias_line = _replace_fixed_width(alias_line, 77, 78, " ")
            f_out.write(alias_line)

    # Kept for traceability and, if necessary, for restoring labels in outputs.
    with alias_map_path.open("w", newline="", encoding="utf-8") as f_out:
        writer = csv.writer(f_out)
        writer.writerow(["station_real", "station_alias"])
        for station in sorted(aliases):
            writer.writerow([station, aliases[station]])

    print(
        f"Created {len(aliases)} temporary Hypoellipse station aliases: "
        f"{alias_map_path.name}"
    )

def _restore_real_station_names(output_path, alias_map_path):
    """
    Replace temporary aliases in Hypoellipse printer output with real station
    names. This changes only location-1D.out, never all.he/out_conv.phs.
    """
    with alias_map_path.open("r", newline="", encoding="utf-8") as f_in:
        alias_to_real = {
            row["station_alias"]: row["station_real"]
            for row in csv.DictReader(f_in)
        }

    text = output_path.read_text(encoding="utf-8")

    for alias, real_station in alias_to_real.items():
        # Hypoellipse may write aliases in lower case, e.g. s001z.
            text = re.sub(
                re.escape(alias),
                real_station,
                text,
                flags=re.IGNORECASE,
            )

    output_path.write_text(text, encoding="utf-8")
    print(f"Restored real station names in {output_path.name}")

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
    temporary_dir = input_dir / "temporary"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    alias_stations_path = temporary_dir / ALIAS_STATIONS_NAME
    alias_phs_path = input_dir / ALIAS_PHS_NAME
    alias_map_path = temporary_dir / ALIAS_MAP_NAME

    _create_alias_inputs(
        stations_path=stations_path,
        phs_path=phs_path,
        alias_stations_path=alias_stations_path,
        alias_phs_path=alias_phs_path,
        alias_map_path=alias_map_path,
    )

    _enable_printer_output(input_dir / PARAMETERS_NAME)

    _write_filecom(
        input_dir / FILECOM_NAME,
        stations_name=f"temporary/{ALIAS_STATIONS_NAME}",
        phs_name=ALIAS_PHS_NAME,
    )
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
    _restore_real_station_names(
        location_1d_out_path,
        Path(ctx.paths.hypoellipse_input_dir) / "temporary" / ALIAS_MAP_NAME,
    )

    print(f"HypoEllipse output written to: {location_1d_out_path}")


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_hypoellipse_check = run


if __name__ == "__main__":
    main()
