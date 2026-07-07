#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse

from seimlai.optional._context import build_optional_context


def main():
    parser = argparse.ArgumentParser(description="Run optional threshold result analysis.")
    parser.add_argument("--config", default="config.yaml", help="Path to the YAML configuration file.")
    args = parser.parse_args()

    from seimlai.threshold_analysis import run

    run(build_optional_context(args.config))


if __name__ == "__main__":
    main()
