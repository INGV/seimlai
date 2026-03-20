#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Nov 21 13:44:05 2025

@author: rossella.fonzetti
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
import re
from config import *

# --- CONFIGURATION ---
# MODEL_TESTED='pretraining_instance'
BASE_DIRECTORY = output_base
FILE_NAME = f"{start_day}_{end_day}_{year}_picks_sort.csv"
LOG_FILE = "analysis_log.txt"
SINGLE_PDF_FILE = "combined_analysis_report.pdf"

# --- Plotting Function (No changes needed, it uses the pre-sorted DataFrame) ---
def generate_combined_plots(df_plot, output_dir):
    """Generates a single PDF file containing 5 combined subplots from the aggregated data."""
    
    # --- Plotting logic remains the same, assumes df_plot is already sorted ---
    thresholds = df_plot['threshold'].astype(str)
    x = np.arange(len(thresholds))
    width = 0.6 

    fig = plt.figure(figsize=(16, 18))
    gs = fig.add_gridspec(3, 2, hspace=0.6, wspace=0.3) 
    
    ax1 = fig.add_subplot(gs[0, 0])  # 1. Count P
    ax2 = fig.add_subplot(gs[0, 1])  # 2. Count S
    ax3 = fig.add_subplot(gs[1, 0])  # 3. Mean Prob P
    ax4 = fig.add_subplot(gs[1, 1])  # 4. Mean Prob S
    ax5 = fig.add_subplot(gs[2, :])  # 5. Std Dev P/S (Line Chart, spans both columns)

    # --- Plot 1: P Count (Bar) ---
    rects1 = ax1.bar(x, df_plot['num_p'], width, color='skyblue')
    ax1.set_ylabel('P-wave Count')
    ax1.set_title('1. P-wave Pick Count vs. Threshold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(thresholds)
    for rect in rects1:
        height = rect.get_height()
        ax1.text(rect.get_x() + rect.get_width()/2., height, f'{height:.0f}', ha='center', va='bottom', fontsize=8)

    # --- Plot 2: S Count (Bar) ---
    rects2 = ax2.bar(x, df_plot['num_s'], width, color='salmon')
    ax2.set_ylabel('S-wave Count')
    ax2.set_title('2. S-wave Pick Count vs. Threshold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(thresholds)
    for rect in rects2:
        height = rect.get_height()
        ax2.text(rect.get_x() + rect.get_width()/2., height, f'{height:.0f}', ha='center', va='bottom', fontsize=8)

    # --- Plot 3: Mean Probability P (Bar with Mean +/- Std Dev label) ---
    rects3 = ax3.bar(x, df_plot['mean_p'], width, color='lightgreen')
    ax3.set_ylabel('Mean Probability')
    ax3.set_title('3. Mean P-wave Probability vs. Threshold (Mean ± Std Dev)')
    ax3.set_xticks(x)
    ax3.set_xticklabels(thresholds)
    for rect, m_p, sd_p in zip(rects3, df_plot['mean_p'], df_plot['std_p']):
        text_label = f'{m_p:.4f} ± {sd_p:.4f}'
        ax3.text(rect.get_x() + rect.get_width()/2., rect.get_height(), text_label, ha='center', va='bottom', fontsize=8)

    # --- Plot 4: Mean Probability S (Bar with Mean +/- Std Dev label) ---
    rects4 = ax4.bar(x, df_plot['mean_s'], width, color='gold')
    ax4.set_ylabel('Mean Probability')
    ax4.set_title('4. Mean S-wave Probability vs. Threshold (Mean ± Std Dev)')
    ax4.set_xticks(x)
    ax4.set_xticklabels(thresholds)
    for rect, m_s, sd_s in zip(rects4, df_plot['mean_s'], df_plot['std_s']):
        text_label = f'{m_s:.4f} ± {sd_s:.4f}'
        ax4.text(rect.get_x() + rect.get_width()/2., rect.get_height(), text_label, ha='center', va='bottom', fontsize=8)

    # --- Plot 5: Std Dev P and S (Combined Line Chart) ---
    ax5.plot(thresholds, df_plot['std_p'], marker='o', linestyle='-', color='blue', label='P-wave Std Dev')
    ax5.plot(thresholds, df_plot['std_s'], marker='s', linestyle='--', color='red', label='S-wave Std Dev')
    ax5.set_ylabel('Standard Deviation of Probability')
    ax5.set_xlabel('Threshold')
    ax5.set_title('5. Probability Standard Deviation vs. Threshold (Combined Line Chart)')
    ax5.legend()
    ax5.grid(True, linestyle=':', alpha=0.6)

    # Apply X-axis rotation to all subplots for readability
    for ax in [ax1, ax2, ax3, ax4, ax5]:
        ax.set_xlabel('Threshold')
        ax.tick_params(axis='x', rotation=45)

    # Save the single combined PDF file in the BASE_DIRECTORY
    output_path = os.path.join(output_dir, SINGLE_PDF_FILE)
    # Ignora il warning di tight_layout (è un problema comune con gridspec su matplotlib, ma il layout è corretto)
    fig.tight_layout() 
    fig.savefig(output_path, format='pdf', dpi=300)
    plt.close(fig)


# --- Main Analysis Function ---
def analyze_data_by_threshold():
    """
    Collects data, sorts it, and generates the single log and the single combined PDF.
    """
    
    if not os.path.exists(BASE_DIRECTORY):
        print(f"ERROR: The defined BASE_DIRECTORY '{BASE_DIRECTORY}' does not exist.")
        return

    log_path = os.path.join(BASE_DIRECTORY, LOG_FILE)
    plot_data = [] # List to collect data from ALL directories
    found_any_data = False

    # --- DATA COLLECTION LOOP ---
    for root, dirs, files in os.walk(BASE_DIRECTORY):
        
        if os.path.basename(root).startswith('output_picks'):
            
            dir_name = os.path.basename(root)
            # Use regex to robustly extract the threshold number from the directory name
            # e.g., 'output_picks_01-01' -> '01'
            match = re.search(r'(\d+\.?\d+)', dir_name) 
            threshold_value = match.group(1) if match else dir_name
            
            if FILE_NAME in files:
                file_path = os.path.join(root, FILE_NAME)
                found_any_data = True
                
                print(f"Aggregating data from: {dir_name} (Threshold: {threshold_value})")

                try:
                    df = pd.read_csv(file_path)
                    df.columns = ['Julian_Day', 'Station', 'Datetime', 'Probability', 'Wave_Type']

                    df_p = df[df['Wave_Type'] == 'p']['Probability']
                    df_s = df[df['Wave_Type'] == 's']['Probability']

                    num_p = len(df_p)
                    num_s = len(df_s)
                    
                    mean_p = df_p.mean() if num_p > 0 else 0.0
                    std_p = df_p.std() if num_p > 1 else 0.0 
                    mean_s = df_s.mean() if num_s > 0 else 0.0
                    std_s = df_s.std() if num_s > 1 else 0.0
                    
                    std_p = 0.0 if np.isnan(std_p) else std_p
                    std_s = 0.0 if np.isnan(std_s) else std_s

                    # Collect data for plotting
                    plot_data.append({
                        'threshold': threshold_value,
                        'num_p': num_p,
                        'num_s': num_s,
                        'mean_p': mean_p,
                        'std_p': std_p,
                        'mean_s': mean_s,
                        'std_s': std_s,
                    })

                except Exception as e:
                    print(f"ERROR: Could not process file in {root}. Details: {e}")
                
    if not found_any_data:
        print("\n--- NO DATA FOUND ---")
        print(f"Could not find '{FILE_NAME}' in any subdirectory starting with 'output_picks_' under '{BASE_DIRECTORY}'.")
        return

    # --- CRITICAL FIX: SORT DATA NUMERICALLY ---
    df_plot = pd.DataFrame(plot_data)
    
    # Force conversion to float for numerical sorting, ignoring errors if conversion fails
    df_plot['threshold_num'] = pd.to_numeric(df_plot['threshold'], errors='coerce') 
    
    # Sort by the numerical column
    df_plot = df_plot.sort_values(by='threshold_num', na_position='last')
    
    # --- LOG WRITING (Using Sorted Data) ---
    # Log file will be overwritten with the sorted data
    with open(log_path, 'w') as log_file:
        log_file.write("=== Probability Analysis by Threshold ===\n\n")
        log_file.write(
            "Threshold\tCount P\tCount S\tMean Prob P\tStd Dev Prob P\tMean Prob S\tStd Dev Prob S\n"
            "------------------------------------------------------------------------------------------------------\n"
        )
        # Write each row from the sorted DataFrame
        for index, row in df_plot.iterrows():
            log_entry = (
                f"{row['threshold']}\t{row['num_p']}\t{row['num_s']}\t{row['mean_p']:.4f}\t{row['std_p']:.4f}\t{row['mean_s']:.4f}\t{row['std_s']:.4f}\n"
            )
            log_file.write(log_entry)
        
    # --- PLOT GENERATION ---
    generate_combined_plots(df_plot, BASE_DIRECTORY)
    
    print(f"\n✅ Analysis complete!")
    print(f"✅ Single log file saved (SORTED) to: {log_path}")
    print(f"✅ Single combined PDF saved to: {os.path.join(BASE_DIRECTORY, SINGLE_PDF_FILE)}")
    
# --- ESECUZIONE ---
# Per eseguire, chiama la funzione:
analyze_data_by_threshold()
