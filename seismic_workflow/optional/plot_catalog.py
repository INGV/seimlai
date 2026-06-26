#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse

from seismic_workflow.optional._context import build_optional_context


def main():
    parser = argparse.ArgumentParser(description="Run optional catalog plotting.")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML configuration file.")
    args = parser.parse_args()

    from seismic_workflow.plotting import run

    run(build_optional_context(args.config))


if __name__ == "__main__":
    main()
