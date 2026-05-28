#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Absolute location stage.

HypoEllipse is currently run outside this Python workflow. This stage checks
that the expected HypoEllipse output is available before downstream steps run.
"""

import os
import sys


def get_location_1d_out_path():
    try:
        from config import location_1d_out_path
        return location_1d_out_path
    except ModuleNotFoundError:
        import ast

        config_values = {}
        with open("config.py", "r") as f:
            tree = ast.parse(f.read(), filename="config.py")

        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name):
                    try:
                        config_values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        pass

        case_study_name = config_values.get("case_study_name", "Amatrice_catalog")
        personal_folder = config_values.get("PERSONAL_FOLDER")
        p_threshold = config_values.get("P_THRESHOLD", 0.1)

        project_root = personal_folder or os.path.join(os.getcwd(), case_study_name)
        return os.path.join(project_root, "output", f"output_catalog_{p_threshold}", "DD", "location-1D.out")


def main():
    location_1d_out_path = get_location_1d_out_path()

    if not os.path.exists(location_1d_out_path):
        print(f"ERROR: HypoEllipse output not found: {location_1d_out_path}")
        print("Run HypoEllipse externally and place location-1D.out in the configured DD folder.")
        sys.exit(1)

    print(f"HypoEllipse output found: {location_1d_out_path}")


if __name__ == "__main__":
    main()
