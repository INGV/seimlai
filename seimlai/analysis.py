#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov 13 10:47:52 2025

@author: rossella.fonzetti
"""
import pandas as pd  
import os        


def run(ctx):
    globals().update(ctx.legacy_globals())


    # Input file name built from config variables
    date_tag_val = date_tag if "date_tag" in globals() else f"{year}_{start_day:03d}_{end_day:03d}"
    input_filename = f"gamma_pick_{date_tag_val}.csv"
    input_file_path = os.path.join(output_dir, input_filename)
    if not os.path.exists(input_file_path):
        legacy_path = os.path.join(output_dir, f"gamma_pick_{year}_{start_day}_{end_day}.csv")
        if os.path.exists(legacy_path):
            input_file_path = legacy_path

    log_file_path = os.path.join(output_dir, analysis_log_filename)

    print(f"Reading file:\n{input_file_path}\n")
    print(f"Saving log file in:\n{log_file_path}\n")

    try:
        df = pd.read_csv(input_file_path)
        print("Input file successfully read.")

        print("Computations in progress...")
        
        is_p = df['type'] == 'p'
        is_s = df['type'] == 's'
        
        total_p = is_p.sum()
        total_s = is_s.sum()

        if pd.api.types.is_float_dtype(df['event_idx']):
            unassoc_condition = (df['event_idx'] == -1.0) | (df['event_idx'] == -1)
            assoc_condition = (df['event_idx'] != -1.0) & (df['event_idx'] != -1)
        else:
            unassoc_condition = df['event_idx'] == -1
            assoc_condition = df['event_idx'] != -1
        
        unassociated_p = (is_p & unassoc_condition).sum()
        unassociated_s = (is_s & unassoc_condition).sum()
        
        associated_p = (is_p & assoc_condition).sum()
        associated_s = (is_s & assoc_condition).sum()
        
        print("Computations completed.")

        with open(log_file_path, 'w', encoding='utf-8') as f:
            f.write(f"File analysis: {input_file_path}\n\n")
            
            f.write("--- TOTAL COUNTS ---\n")
            f.write(f"P-wave total: {total_p}\n")
            f.write(f"S-wave total: {total_s}\n")
            
            f.write("\n--- UNASSOCIATED PICKS (event_idx = -1) ---\n")
            f.write(f"Unassociated P-wave: {unassociated_p}\n")
            f.write(f"Unassociated S-wave: {unassociated_s}\n")
            
            f.write("\n--- ASSOCIATED PICKS (event_idx != -1) ---\n")
            f.write(f"Associated P-wave: {associated_p}\n")
            f.write(f"Associated S-wave: {associated_s}\n")
        
        print(f"\n--- OPERATION COMPLETED ---")
        print(f"Log file created successfully in:\n{log_file_path}")

    # --- 8. ERROR HANDLING ---
    except FileNotFoundError:
        print(f"\n--- ERROR ---")
        print(f"File not found. Check that the path is correct:")
        print(f"{input_file_path}")
        
    except KeyError as e:
        print(f"\n--- ERROR ---")
        print(f"Column not found: {e}. Check that the CSV file contains the columns 'type' and 'event_idx'.")

    except Exception as e:
        print(f"\n--- UNEXPECTED ERROR ---")
        print(f"An error occurred: {e}")


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_analysis = run


if __name__ == "__main__":
    main()
