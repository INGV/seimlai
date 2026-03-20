#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Aug  7 09:54:47 2025

@author: rossella.fonzetti
"""

########################################################################
# This sciprt convert stations file from csv format to .he (useful to Hypoellipse running)
########################################################################

import pandas as pd
import os
from config import *

def dec_to_degmin(dec_deg, is_lat=True):
    """
    Convert decimal degrees to degrees + minutes format.
    Example: 42.8295 → '42N49.77'
    """
    degrees = int(dec_deg)
    minutes = abs(dec_deg - degrees) * 60
    direction = ('N' if dec_deg >= 0 else 'S') if is_lat else ('E' if dec_deg >= 0 else 'W')
    return f"{abs(degrees):02d}{direction}{minutes:05.2f}"

# Load the CSV file
df = pd.read_csv(os.path.join(case_study_dir, station_file_name))

# Create output directory if it doesn't exist
os.makedirs(h71_filtered_dir, exist_ok=True)

# List to store output lines
lines = []

for _, row in df.iterrows():
    code_full = str(row["station"])
    code_len = len(code_full)
    code = code_full[:5]

    lat = dec_to_degmin(row["latitude"], is_lat=True)
    lon = dec_to_degmin(row["longitude"], is_lat=False)
    elev = int(round(row["elevation"]))  # elevation in meters
    depth = 0
    weight = 1.00

    # Format elevation right-aligned, fixed width 5
    elev_str = f"{elev:>5}"

    # Line 1: handle spacing and 5-char rule
    if code_len == 3:
        line1 = f" {code}{lat}  {lon}{elev_str}"
    elif code_len == 4:
        line1 = f"{code:<4}{lat}  {lon}{elev_str}"
    elif code_len >= 5:
        base_line1 = f"{code[:4]:<4}{lat}  {lon}{elev_str}"
        padding = " " * max(0, 79 - len(base_line1))
        line1 = base_line1 + padding + code[4]
    else:
        line1 = f"{code[:4]:<4}{lat}  {lon}{elev_str}"

    # Line 2: same alignment logic
    if code_len == 3:
        line2 = f" {code}*{depth:6d}{weight:10.2f}"
    elif code_len == 4:
        line2 = f"{code[:4]:<4}*{depth:6d}{weight:10.2f}"
    elif code_len >= 5:
        base_line2 = f"{code[:4]:<4}*{depth:6d}{weight:10.2f}"
        padding2 = " " * max(0, 79 - len(base_line2))
        line2 = base_line2 + padding2 + code[4]
    else:
        line2 = f"{code[:4]:<4}*{depth:6d}{weight:10.2f}"

    lines.append(line1)
    lines.append(line2)

# Save to file
output_path = os.path.join(h71_filtered_dir, "all.he")
with open(output_path, "w") as f:
    for line in lines:
        f.write(line + "\n")
