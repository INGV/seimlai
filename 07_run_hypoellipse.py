#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Aug  8 10:53:16 2025

@author: rossella.fonzetti
"""

########################################################################
# This sciprt run Hypoellipse inside a python scritp
########################################################################

import subprocess
from pathlib import Path
import shutil

# Define working directory
wdir = Path("/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/TEST_AQ2009_MODEL/RELOC_HYPOELLIPSE")

# Define real input files
original_phs = wdir / "out_conv.phs"
original_cfg = wdir.parent / "X-LOCATION" / "improved.cfg"

# Define expected alias filenames
alias_phs = wdir / "get_picks_sac.phs"
alias_cfg = wdir / "location.par.cfg"

# Create alias files by copying
print("🔁 Creating alias files...")

if original_phs.exists():
    shutil.copy(original_phs, alias_phs)
    print(f"✅ Copied {original_phs.name} → {alias_phs.name}")
else:
    print(f"❌ Missing file: {original_phs}")

if original_cfg.exists():
    shutil.copy(original_cfg, alias_cfg)
    print(f"✅ Copied {original_cfg.name} → {alias_cfg.name}")
else:
    print(f"❌ Missing file: {original_cfg}")

# Prepare script execution
script_path = "/Users/rossella.fonzetti/WORK/PROGRAMMI/HYMAIN-LOC-5-CAR/hypoell-loc-5-car.sh"
input_filename = "hypoell-loc-5-car.inp"

print("\n🚀 Running hypoellipse script...\n")

result = subprocess.run(
    ["bash", script_path, input_filename],
    cwd=wdir,
    capture_output=True,
    text=True
)

# Show output
print("========== STDOUT ==========")
print(result.stdout)

print("\n========== STDERR ==========")
print(result.stderr)

print("Return code:", result.returncode)