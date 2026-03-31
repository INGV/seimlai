#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline runner: executes all scripts from 01 to 06 in order.
Usage:
    python run.py            # run all steps
    python run.py --from 03  # start from a specific step
    python run.py --only 04_1 04_2  # run only specific steps
"""

import subprocess
import sys
import time
import argparse

# ============================================================
# PIPELINE DEFINITION
# Each entry: (step_id, script_filename, description)
# ============================================================
PIPELINE = [
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
STEP IDs (in pipeline order):
  01      Download waveforms
  02_1    Apply phase picking using NN
  03      Sort and consolidate picks
  03_1    Analyse prediction metrics
  04_1    Run GaMMA association
  04_2    Analyse GaMMA output
  04_3    Plot catalog (PyGMT)
  05      Create .phs and .h71 files
  06      Convert station file to .he

EXAMPLES:
  # Run the full pipeline from start to finish:
  python run.py

  # Start from step 03 (skip download and picking):
  python run.py --from 03

  # Resume after GaMMA, starting from step 04_2:
  python run.py --from 04_2

  # Run only the location-preparation steps (05 and 06):
  python run.py --only 05 06

  # Re-run only the GaMMA analysis and plot steps:
  python run.py --only 04_1 04_2 04_3
"""
    parser = argparse.ArgumentParser(
        description="Seismic pipeline runner — executes scripts 01 to 06 in order.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog,
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
    steps_to_run = PIPELINE

    if args.from_step:
        ids = [s[0] for s in PIPELINE]
        if args.from_step not in ids:
            print(f"[ERROR] Unknown step ID '{args.from_step}'. Valid IDs: {ids}")
            sys.exit(1)
        idx = ids.index(args.from_step)
        steps_to_run = PIPELINE[idx:]

    elif args.only_steps:
        ids = [s[0] for s in PIPELINE]
        for s in args.only_steps:
            if s not in ids:
                print(f"[ERROR] Unknown step ID '{s}'. Valid IDs: {ids}")
                sys.exit(1)
        steps_to_run = [s for s in PIPELINE if s[0] in args.only_steps]

    print(f"\n{'#'*60}")
    print(f"  SEISMIC PIPELINE — {len(steps_to_run)} step(s) to run")
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
