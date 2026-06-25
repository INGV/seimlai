#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from _bootstrap import add_repo_root_to_path, build_cli_context

add_repo_root_to_path()
from seismic_workflow.phase_picking import run


if __name__ == "__main__":
    run(build_cli_context("config.yaml"))
