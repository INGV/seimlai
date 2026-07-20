#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data cleaning stage.

The current workflow does not apply additional cleaning between download and
phase picking. This file exists to keep the pipeline structure explicit.
"""

def run(ctx):
    print("No additional data cleaning configured. Existing waveform and inventory files are unchanged.")


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_data_cleaning = run


if __name__ == "__main__":
    main()
