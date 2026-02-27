#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 30 12:23:32 2026

@author: rossella.fonzetti
"""

import matplotlib.pyplot as plt
import os
import re

# --- 1. Path Configuration ---
# Update 'model' and 'base_dir' to match your local environment
model = "PRETRAINED_ORIGINAL"
#EP_41_PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_crossentropy_
#PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_focalloss_
#PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_transferlearning_crossentropy_
#PN_60_epochs_4096_bs_0.0001_lr_std_norm.AQ2009_transferlearning_focalloss_20250627_143520_
base_dir = f"/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/{model}"
threshold = "01-01"

input_file_name = f'location-1D_{threshold}.out'
pdf_output_file = f'residuals_quad_histograms_{threshold}.pdf'

full_input_path = os.path.join(base_dir, input_file_name)
full_output_path = os.path.join(base_dir, pdf_output_file)

# --- 2. Filter Criteria ---
FILTER_GAP = 180.0
FILTER_RMS = 0.6
FILTER_SEH = 1.5
FILTER_SEZ = 1.5

# Lists to store residuals
p_res_all = []
s_res_all = []
p_res_filtered = []
s_res_filtered = []

# Debug counters
stats = {'total_events': 0, 'passed_filters': 0}

# --- 3. Parsing the .out file ---
try:
    if not os.path.exists(full_input_path):
        raise FileNotFoundError(f"File not found: {full_input_path}")

    with open(full_input_path, 'r') as f:
        content = f.read()

    # Split the file by each earthquake event
    event_blocks = content.split("earthquake location")
    
    for block in event_blocks[1:]:
        stats['total_events'] += 1
        lines = block.split('\n')
        gap = rms = seh = sez = None
        
        # --- A. Extract Quality Parameters ---
        for i, line in enumerate(lines):
            # Try to get GAP and RMS from summary table
            if 'gap d  rms' in line and i + 1 < len(lines):
                parts = lines[i+1].split()
                if len(parts) >= 11:
                    gap = float(parts[-5])
                    rms = float(parts[-3])
            
            # Try to get SEH and SEZ from summary table
            if 'seh  sez q sqd' in line and i + 1 < len(lines):
                parts = lines[i+1].split()
                if len(parts) >= 2:
                    seh = float(parts[0])
                    sez = float(parts[1])

        # Backup: regex search if tables are messy
        if seh is None:
            m = re.search(r"seh\s*=\s*([\d\.]+)", block)
            if m: seh = float(m.group(1))
        if sez is None:
            m = re.search(r"sez\s*=\s*([\d\.]+)", block)
            if m: sez = float(m.group(1))
        if rms is None:
            m = re.search(r"se of orig\s*=\s*([\d\.]+)", block)
            if m: rms = float(m.group(1))

        # Check filter status
        is_filtered = False
        if all(v is not None for v in [gap, rms, seh, sez]):
            if gap < FILTER_GAP and rms < FILTER_RMS and seh < FILTER_SEH and sez < FILTER_SEZ:
                is_filtered = True
                stats['passed_filters'] += 1

        # --- B. Extract Residuals ---
        in_travel_times = False
        for line in lines:
            if "-- travel times and delays --" in line:
                in_travel_times = True
                continue
            if in_travel_times:
                if len(line.strip()) == 0 or "---" in line: continue
                
                parts = line.split()
                if len(parts) < 5: continue
                
                res_val = None
                phase_type = None

                try:
                    # Logic: identify phase and capture the value in 'resid' column
                    if 'EP' in parts or 'P' in parts:
                        phase_type = 'P'
                        idx = parts.index('EP') if 'EP' in parts else parts.index('P')
                        res_val = float(parts[idx+3])
                    elif 'ES' in parts or 'S' in parts:
                        phase_type = 'S'
                        idx = parts.index('ES') if 'ES' in parts else parts.index('S')
                        res_val = float(parts[idx+3])
                    
                    if res_val is not None:
                        # Add to "All" lists
                        if phase_type == 'P': p_res_all.append(res_val)
                        else: s_res_all.append(res_val)
                        
                        # Add to "Filtered" lists if event passed criteria
                        if is_filtered:
                            if phase_type == 'P': p_res_filtered.append(res_val)
                            else: s_res_filtered.append(res_val)
                except: continue

    # --- 4. Plotting (2x2 Layout) ---
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    fig.suptitle(f'Residuals Analysis - File: {input_file_name}\nFilters: GAP<{FILTER_GAP}, RMS<{FILTER_RMS}, SEH/SEZ<{FILTER_SEH}', 
                 fontsize=16, fontweight='bold')

    color_code = '#4682B4' # SteelBlue
    
    # Configuration for the 4 plots
    plot_configs = [
        {'data': p_res_all,      'ax': axes[0, 0], 'title': f'P Residuals - All Events (N={len(p_res_all)})'},
        {'data': s_res_all,      'ax': axes[0, 1], 'title': f'S Residuals - All Events (N={len(s_res_all)})'},
        {'data': p_res_filtered, 'ax': axes[1, 0], 'title': f'P Residuals - Filtered (N={len(p_res_filtered)})'},
        {'data': s_res_filtered, 'ax': axes[1, 1], 'title': f'S Residuals - Filtered (N={len(s_res_filtered)})'}
    ]

    for config in plot_configs:
        ax = config['ax']
        if config['data']:
            ax.hist(config['data'], bins=50, color=color_code, edgecolor=None, rwidth=1.0, alpha=0.9)
        
        ax.set_title(config['title'], fontsize=13, fontweight='semibold')
        ax.set_xlabel('Residual (s)', fontsize=11)
        ax.set_ylabel('Frequency', fontsize=11)
        ax.grid(axis='y', linestyle='--', alpha=0.3)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(full_output_path, dpi=300)
    
    print(f"\nProcessing complete.")
    print(f"Total events: {stats['total_events']}")
    print(f"Events passing filters: {stats['passed_filters']}")
    print(f"Output saved to: {full_output_path}")

except Exception as e:
    print(f"Error: {e}")
