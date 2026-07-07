#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seismic workflow runner.

Usage:
    python main.py
    python main.py continue
    python main.py 03
    python main.py --from 03
    python main.py --only 04 05
    python main.py gamma-analysis
    python main.py plot-catalog
    python main.py threshold-analysis
    python main.py cc-dd-test
    python -m seimlai.main
"""

import argparse
import sys
import time
from dataclasses import dataclass
from importlib import import_module
from typing import Callable

from seimlai.context import build_context, ensure_initial_directories


@dataclass(frozen=True)
class Step:
    id: str
    command: str
    description: str
    module: str
    optional: bool = False

    def load_runner(self) -> Callable:
        return import_module(self.module).run


STEPS = [
    Step("01", "download", "Download data", "seimlai.download"),
    Step("02", "data-cleaning", "Data cleaning", "seimlai.data_cleaning"),
    Step("03", "phase-picking", "Phase picking (CNN)", "seimlai.phase_picking"),
    Step("04", "association", "Phase association and raw catalog building (GaMMA)", "seimlai.association"),
    Step("05", "absolute-location-prep", "Data preparation for absolute location", "seimlai.absolute_location_prep"),
    Step("06", "hypoellipse-check", "Absolute location (HypoEllipse Docker run)", "seimlai.hypoellipse_check"),
    Step("07", "locations-filtering", "Locations filtering", "seimlai.location_filtering"),
    Step("08", "relative-relocation", "Relative relocation (HypoDD input generation)", "seimlai.relative_relocation"),
]

OPTIONAL_STEPS = {
    "gamma-analysis": Step("gamma-analysis", "gamma-analysis", "Analyse GaMMA output", "seimlai.analysis", optional=True),
    "plot-catalog": Step("plot-catalog", "plot-catalog", "Plot catalog (PyGMT)", "seimlai.plotting", optional=True),
    "threshold-analysis": Step("threshold-analysis", "threshold-analysis", "Analyse threshold results", "seimlai.threshold_analysis", optional=True),
    "cc-dd-test": Step("cc-dd-test", "cc-dd-test", "Cross-correlation DD test", "seimlai.cc_dd_test", optional=True),
}

STEP_IDS = [step.id for step in STEPS]


def continue_steps():
    return STEPS[5:]


def run_step(step, ctx):
    """Run a single pipeline step and return True on success."""
    print(f"\n{'='*60}")
    print(f"  STEP {step.id:>5}  |  {step.description}")
    print(f"  Module: {step.module}")
    print(f"{'='*60}")
    sys.stdout.flush()
    t0 = time.time()
    try:
        step.load_runner()(ctx)
    except SystemExit as exc:
        if exc.code not in (0, None):
            print(f"\n[ERROR] Step {step.id} failed (exit code {exc.code}). Pipeline stopped.")
            return False
        raise
    except Exception as exc:
        print(f"\n[ERROR] Step {step.id} failed: {exc}")
        return False
    elapsed = time.time() - t0
    print(f"\n[OK] Step {step.id} completed in {elapsed:.1f}s")
    return True


def parse_args():
    epilog = """
COMMANDS:
  (none)              Run the full workflow.
  continue            Continue from the HypoEllipse output check (steps 06-08).
  01 ... 08           Run one workflow stage by ID.
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
  06  Absolute location (HypoEllipse Docker run)
  07  Locations filtering
  08  Relative relocation (HypoDD input generation)

EXAMPLES:
  python main.py
  python main.py continue
  python main.py 03
  python main.py --from 03
  python main.py --only 06 07
  python main.py gamma-analysis
  python main.py --config config.yaml --only 02
  python -m seimlai.main --config config.yaml --only 02
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
        choices=["continue", *STEP_IDS, *OPTIONAL_STEPS.keys()],
        help="Optional command or stage ID to run instead of the full workflow.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the YAML configuration file.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--from",
        dest="from_step",
        metavar="STEP_ID",
        help="Start pipeline from this step ID.",
    )
    group.add_argument(
        "--only",
        dest="only_steps",
        metavar="STEP_ID",
        nargs="+",
        help="Run only these step IDs.",
    )
    return parser.parse_args()


def select_steps(pipeline, ctx, from_step=None, only_steps=None, phase_label="workflow"):
    steps_to_run = pipeline

    if from_step:
        ids = [s.id for s in pipeline]
        if from_step not in ids:
            print(f"[ERROR] Unknown step ID '{from_step}'. Valid IDs for {phase_label}: {ids}")
            sys.exit(1)
        idx = ids.index(from_step)
        steps_to_run = pipeline[idx:]

    elif only_steps:
        ids = [s.id for s in pipeline]
        for step_id in only_steps:
            if step_id not in ids:
                print(f"[ERROR] Unknown step ID '{step_id}'. Valid IDs for {phase_label}: {ids}")
                sys.exit(1)
        steps_to_run = [s for s in pipeline if s.id in only_steps]

    if any(step.id == "01" for step in steps_to_run):
        if ctx.raw.case_study["personal_folder"] is not None and not ctx.raw.case_study["download_data"]:
            steps_to_run = [s for s in steps_to_run if s.id != "01"]

    return steps_to_run


def run_pipeline(ctx, pipeline, phase_label, from_step=None, only_steps=None):
    steps_to_run = select_steps(pipeline, ctx, from_step, only_steps, phase_label)

    print(f"\n{'#'*60}")
    print(f"  SEISMIC WORKFLOW - {phase_label}")
    print(f"  {len(steps_to_run)} step(s) to run")
    print(f"{'#'*60}")
    for step in steps_to_run:
        print(f"  [{step.id:>2}] {step.description}")

    total_start = time.time()
    for step in steps_to_run:
        if not run_step(step, ctx):
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f"\n{'#'*60}")
    print(f"  ALL STEPS COMPLETED in {total_elapsed:.1f}s")
    print(f"{'#'*60}\n")


def run_optional_command(ctx, command):
    step = OPTIONAL_STEPS[command]
    if not run_step(step, ctx):
        sys.exit(1)


def run_single_stage(ctx, step_id):
    step_map = {step.id: step for step in STEPS}
    if not run_step(step_map[step_id], ctx):
        sys.exit(1)


def main():
    args = parse_args()
    try:
        ctx = build_context(args.config)
    except Exception as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)
    ensure_initial_directories(ctx)

    if args.command in STEP_IDS:
        if args.from_step or args.only_steps:
            print("[ERROR] --from and --only cannot be used when running a single stage ID command.")
            sys.exit(1)
        run_single_stage(ctx, args.command)
        return

    if args.command in OPTIONAL_STEPS:
        if args.from_step or args.only_steps:
            print("[ERROR] --from and --only can only be used with the main workflow or continue.")
            sys.exit(1)
        run_optional_command(ctx, args.command)
        return

    if args.command == "continue":
        run_pipeline(
            ctx,
            continue_steps(),
            "continue (steps 06-08)",
            from_step=args.from_step,
            only_steps=args.only_steps,
        )
    else:
        run_pipeline(
            ctx,
            STEPS,
            "full workflow",
            from_step=args.from_step,
            only_steps=args.only_steps,
        )


if __name__ == "__main__":
    main()
