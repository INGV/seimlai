#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import matplotlib.pyplot as plt
import os  # Import the 'os' library to manage paths

# --- 1. Define Paths and Threshold ---

# The base directory you specified
#base_dir="/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_transferlearning_crossentropy_"
#base_dir="/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/EP_41_PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_crossentropy_"
#base_dir="/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_focalloss_"
#base_dir = "/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/PN_60_epochs_4096_bs_0.0001_lr_std_norm.AQ2009_transferlearning_focalloss_20250627_143520_"
base_dir="/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/PRETRAINED_ORIGINAL"
threshold = "01-01"

# File names
input_file_name = f'location-1D_{threshold}.quality'
pdf_output_file = f'histograms_{threshold}.pdf'

# Use os.path.join to build the full paths
full_input_path = os.path.join(base_dir, input_file_name)
full_output_path = os.path.join(base_dir, pdf_output_file)

# List of columns to analyze
columns_to_plot = ['N_P', 'N_S', 'GAP', 'RMS_HE', 'SEH', 'SEZ']

# Control message for the user (in English)
print(f"Input path: {full_input_path}")
print(f"Output PDF path: {full_output_path}")

# --- 2. Execution ---
try:
    # Load the file using the full path
    df = pd.read_csv(full_input_path, delim_whitespace=True)
    
    print(f"File '{input_file_name}' loaded successfully.")

    # --- Create Subplots ---
    fig, axes = plt.subplots(nrows=3, ncols=2, figsize=(10, 12))
    
    # Add the main title (as requested previously)
    main_title = f'Histograms of 1D locations (threshold = {threshold})'
    fig.suptitle(main_title, fontsize=16, y=1.03)
    
    print("Generating histograms...")
    
    for ax, col_name in zip(axes.flat, columns_to_plot):
        
        # --- Handle Sentinel Values (Outliers) ---
        # *** THIS IS THE FIX ***
        # 'plot_title' is now defined in BOTH branches of the if/else
        
        if col_name in ['SEH', 'SEZ']:
            data_to_plot = df[col_name][df[col_name] < 99]
            plot_title = f'Histogram of {col_name} (values < 99)' # Defined here
        else:
            data_to_plot = df[col_name]
            plot_title = f'Histogram of {col_name}' # Defined here

        # --- Plot Histogram ---
        ax.hist(data_to_plot, bins=100, edgecolor='k', alpha=0.75)
        
        # --- Set Labels and Titles (in English) ---
        ax.set_title(plot_title)
        ax.set_xlabel('Value') # Corrected to English
        ax.set_ylabel('Frequency (Count)') # Corrected to English
        ax.grid(True, linestyle='--', alpha=0.6)

    # --- Optimize Layout and Save ---
    plt.tight_layout()
    
    # Adjust layout to make space for the main title (suptitle)
    fig.subplots_adjust(top=0.94)
    
    # Save the figure to the full output path
    plt.savefig(full_output_path, dpi=300, format='pdf')
    
    print(f"\nOperation completed successfully!")
    print(f"PDF file created in: {full_output_path} (at 300 DPI)")

# --- Error Handling (in English) ---
except FileNotFoundError:
    print(f"\n--- ERROR ---")
    print(f"File not found. Please check the path:")
    print(f"{full_input_path}")
except KeyError as e:
    print(f"\n--- ERROR ---")
    print(f"Column {e} not found in file.")
except Exception as e:
    print(f"\n--- UNEXPECTED ERROR ---")
    print(f"An error occurred: {e}")
