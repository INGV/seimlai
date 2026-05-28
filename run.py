#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline runner: executes workflow stages in order.

Usage:
    python run.py
    python run.py continue
    python run.py --from 03
    python run.py --only 04 05
    python run.py gamma-analysis
    python run.py plot-catalog
    python run.py threshold-analysis
    python run.py cc-dd-test
"""

import argparse
import subprocess
import sys
import time


MAIN_PIPELINE = [
    ("01", "01_download_data.py", "Download data"),
    ("02", "02_data_cleaning.py", "Data cleaning"),
    ("03", "03_phase_picking_cnn.py", "Phase picking (CNN)"),
    ("04", "04_phase_association_raw_catalog_building_gamma.py", "Phase association and raw catalog building (GaMMA)"),
    ("05", "05_data_preparation_for_absolute_location.py", "Data preparation for absolute location"),
    ("06", "06_absolute_location_hypoellipse.py", "Absolute location (HypoEllipse output check)"),
    ("07", "07_locations_filtering.py", "Locations filtering"),
    ("08", "08_relative_relocation_hypodd.py", "Relative relocation (HypoDD input generation)"),
]

CONTINUE_PIPELINE = MAIN_PIPELINE[5:]

OPTIONAL_COMMANDS = {
    "gamma-analysis": ("gamma-analysis.py", "Analyse GaMMA output"),
    "plot-catalog": ("plot-catalog.py", "Plot catalog (PyGMT)"),
    "threshold-analysis": ("12_analyse_thr_results.py", "Analyse threshold results"),
    "cc-dd-test": ("11_cc_DD_non_testato.py", "Cross-correlation DD test"),
}


def run_step(step_id, script, description):
    """Run a single pipeline step and return True on success."""
    print(f"\n{'='*60}")
    print(f"  STEP {step_id:>5}  |  {description}")
    print(f"  Script: {script}")
    print(f"{'='*60}")
    sys.stdout.flush()
    t0 = time.time()
    result = subprocess.run([sys.executable, script], capture_output=False)
    elapsed = time.time() - t0
    if result.returncode != 0:
        print(f"\n[ERROR] Step {step_id} failed (exit code {result.returncode}). Pipeline stopped.")
        return False
    print(f"\n[OK] Step {step_id} completed in {elapsed:.1f}s")
    return True


def parse_args():
    epilog = """
COMMANDS:
  (none)              Run the full workflow.
  continue            Continue from the HypoEllipse output check (steps 06-08).
  gamma-analysis      Run optional GaMMA output analysis.
  plot-catalog        Run optional catalog plotting.
  threshold-analysis  Run optional threshold analysis.
  cc-dd-test          Run optional experimental cross-correlation DD test.

STEP IDs:
  01  Download data
  02  Data cleaning
  03  Phase picking (CNN)
  04  Phase association and raw catalog building (GaMMA)
  05  Data preparation for absolute location
  06  Absolute location (HypoEllipse output check)
  07  Locations filtering
  08  Relative relocation (HypoDD input generation)

EXAMPLES:
  python run.py
  python run.py continue
  python run.py --from 03
  python run.py --only 06 07
  python run.py gamma-analysis
"""
    parser = argparse.ArgumentParser(
        description="Seismic workflow runner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        choices=["continue", *OPTIONAL_COMMANDS.keys()],
        help="Optional command to run instead of the full workflow."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--from",
        dest="from_step",
        metavar="STEP_ID",
        help="Start pipeline from this step ID."
    )
    group.add_argument(
        "--only",
        dest="only_steps",
        metavar="STEP_ID",
        nargs="+",
        help="Run only these step IDs."
    )
    return parser.parse_args()


def select_steps(pipeline, from_step=None, only_steps=None, phase_label="workflow"):
    steps_to_run = pipeline

    if from_step:
        ids = [s[0] for s in pipeline]
        if from_step not in ids:
            print(f"[ERROR] Unknown step ID '{from_step}'. Valid IDs for {phase_label}: {ids}")
            sys.exit(1)
        idx = ids.index(from_step)
        steps_to_run = pipeline[idx:]

    elif only_steps:
        ids = [s[0] for s in pipeline]
        for step_id in only_steps:
            if step_id not in ids:
                print(f"[ERROR] Unknown step ID '{step_id}'. Valid IDs for {phase_label}: {ids}")
                sys.exit(1)
        steps_to_run = [s for s in pipeline if s[0] in only_steps]

    if any(step[0] == "01" for step in steps_to_run):
        try:
            from config import PERSONAL_FOLDER, DOWNLOAD_DATA
        except ModuleNotFoundError:
            PERSONAL_FOLDER = None
            DOWNLOAD_DATA = True

        if PERSONAL_FOLDER is not None and not DOWNLOAD_DATA:
            steps_to_run = [s for s in steps_to_run if s[0] != "01"]

    return steps_to_run


def run_pipeline(pipeline, phase_label, from_step=None, only_steps=None):
    steps_to_run = select_steps(pipeline, from_step, only_steps, phase_label)

    print(f"\n{'#'*60}")
    print(f"  SEISMIC WORKFLOW - {phase_label}")
    print(f"  {len(steps_to_run)} step(s) to run")
    print(f"{'#'*60}")
    for step in steps_to_run:
        print(f"  [{step[0]:>2}] {step[2]}")

    total_start = time.time()
    for step_id, script, description in steps_to_run:
        if not run_step(step_id, script, description):
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f"\n{'#'*60}")
    print(f"  ALL STEPS COMPLETED in {total_elapsed:.1f}s")
    print(f"{'#'*60}\n")


def run_optional_command(command):
    script, description = OPTIONAL_COMMANDS[command]
    if not run_step(command, script, description):
        sys.exit(1)


def main():
    args = parse_args()

    if args.command in OPTIONAL_COMMANDS:
        if args.from_step or args.only_steps:
            print("[ERROR] --from and --only can only be used with the main workflow or continue.")
            sys.exit(1)
        run_optional_command(args.command)
        return

    if args.command == "continue":
        run_pipeline(
            CONTINUE_PIPELINE,
            "continue (steps 06-08)",
            from_step=args.from_step,
            only_steps=args.only_steps,
        )
    else:
        run_pipeline(
            MAIN_PIPELINE,
            "full workflow",
            from_step=args.from_step,
            only_steps=args.only_steps,
        )


if __name__ == "__main__":
    main()
