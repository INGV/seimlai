#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline runner: executes scripts in order.
Usage:
    python run.py            # run scripts 01 to 06
    python run.py continue   # run scripts 08 to 12 (requires location-1D.out)
    python run.py --from 03  # start from a specific step (phase 1 only)
    python run.py --only 04_1 04_2  # run only specific steps
"""

import subprocess
import sys
import time
import argparse
from config import *

# ============================================================
# PIPELINE DEFINITION
# Each entry: (step_id, script_filename, description)
# ============================================================
PIPELINE_PHASE1 = [
    ("01",    "01_download_parallel.py",                    "Download waveforms"),
    ("02_1",  "02_1_apply_and_visualize_picks_priority.py", "Apply phase picking using NN"),
    ("03",    "03_sort_picks.py",                          "Sort and consolidate picks"),
    ("03_1",  "03_1_analyse_prediction_metrics.py",         "Analyse prediction metrics"),
    ("04_1",  "04_1_built_the_catalog_opt.py",              "Run GaMMA association"),
    ("04_2",  "04_2_analyze_GaMMAoutput.py",               "Analyse GaMMA output"),
    ("04_3",  "04_3_plot_catalog.py",                      "Plot catalog (PyGMT)"),
    ("05",    "05_create_phs_h71_new.py",                   "Create .phs and .h71 files"),
    ("06",    "06_convert_stationfile.py",                  "Convert station file to .he"),
]

PIPELINE_PHASE2 = [
    ("08", "08_create_location_quality_file_v2new.py", "Create location quality file"),
    ("10", "10_create_dd_files.py",                     "Create hypoDD input files"),
    ("11", "11_cc_DD_non_testato.py",                   "Cross-correlation DD (experimental)"),
    ("12", "12_analyse_thr_results.py",                 "Analyse threshold results"),
]


def run_step(step_id, script, description):
    """Run a single pipeline step and return True on success."""
    print(f"\n{'='*60}")
    print(f"  STEP {step_id:>5}  |  {description}")
    print(f"  Script: {script}")
    print(f"{'='*60}")
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
  (none)     Run Phase 1: scripts 01 to 06
  continue   Run Phase 2: scripts 08 to 12 (requires location-1D.out from Hypoellipse)

STEP IDs (in pipeline order):
  Phase 1:
    01      Download waveforms
    02_1    Apply phase picking using NN
    03      Sort and consolidate picks
    03_1    Analyse prediction metrics
    04_1    Run GaMMA association
    04_2    Analyse GaMMA output
    04_3    Plot catalog (PyGMT)
    05      Create .phs and .h71 files
    06      Convert station file to .he
  Phase 2 (continue):
    08      Create location quality file
    10      Create hypoDD input files
    11      Cross-correlation DD (experimental)
    12      Analyse threshold results

EXAMPLES:
  # Run Phase 1 (scripts 01-06):
  python run.py

  # Run Phase 2 (scripts 08-12):
  python run.py continue

  # Start Phase 1 from step 03 (skip download and picking):
  python run.py --from 03

  # Start Phase 2 from step 11:
  python run.py continue --from 11

  # Run only specific steps:
  python run.py --only 05 06

  # Run only specific Phase 2 steps:
  python run.py continue --only 11 12
"""
    parser = argparse.ArgumentParser(
        description="Seismic pipeline runner — executes scripts in order.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
    )
    parser.add_argument(
        "command", nargs="?", default=None,
        choices=["continue"],
        help="Use 'continue' to run Phase 2 (scripts 08-12). Omit for Phase 1 (01-06)."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--from", dest="from_step", metavar="STEP_ID",
        help="Start pipeline from this step ID (e.g. 03, 04_1)"
    )
    group.add_argument(
        "--only", dest="only_steps", metavar="STEP_ID", nargs="+",
        help="Run only these step IDs (e.g. --only 05 06)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Select which phase to run
    if args.command == "continue":
        pipeline = PIPELINE_PHASE2
        phase_label = "Phase 2 (scripts 08-12)"
    else:
        pipeline = PIPELINE_PHASE1
        phase_label = "Phase 1 (scripts 01-06)"

    steps_to_run = pipeline

    if args.from_step:
        ids = [s[0] for s in pipeline]
        if args.from_step not in ids:
            print(f"[ERROR] Unknown step ID '{args.from_step}'. Valid IDs for {phase_label}: {ids}")
            sys.exit(1)
        idx = ids.index(args.from_step)
        steps_to_run = pipeline[idx:]

    elif args.only_steps:
        ids = [s[0] for s in pipeline]
        for s in args.only_steps:
            if s not in ids:
                print(f"[ERROR] Unknown step ID '{s}'. Valid IDs for {phase_label}: {ids}")
                sys.exit(1)
        steps_to_run = [s for s in pipeline if s[0] in args.only_steps]

    # Filter out step 01 if PERSONAL_FOLDER is set AND DOWNLOAD_DATA is False
    if PERSONAL_FOLDER is not None and not DOWNLOAD_DATA:
        steps_to_run = [s for s in steps_to_run if s[0] != "01"]

    print(f"\n{'#'*60}")
    print(f"  SEISMIC PIPELINE — {phase_label}")
    print(f"  {len(steps_to_run)} step(s) to run")
    print(f"{'#'*60}")
    for s in steps_to_run:
        print(f"  [{s[0]:>5}] {s[2]}")

    total_start = time.time()
    for step_id, script, description in steps_to_run:
        if not run_step(step_id, script, description):
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f"\n{'#'*60}")
    print(f"  ALL STEPS COMPLETED in {total_elapsed:.1f}s")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
