#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jul 29 10:25:28 2025

@author: rossella.fonzetti
"""


import os
import pandas as pd
from config import *

## SORT PICKING ##
def sort_seismic_picking(df, output_file):
    # Rename columns

    # Rename columns
    df = df.rename(columns={
        "station": "Station",
        "timestamp": "Datetime",
        "prob": "Probability",
        "type": "Wave_Type",
        "amp": "Amplitude"
    })

    # Convert Datatime column
    df["Datetime"] = pd.to_datetime(df["Datetime"])

    # Giulian Name computation (1-366)
    df["Julian_Day"] = df["Datetime"].dt.dayofyear

    # Rename Columns
    column_order = ["Julian_Day", "Station", "Datetime", "Probability", "Amp", "Wave_Type"]
    df = df[column_order]

    # Sort picks
    df_sorted = df.sort_values(by="Datetime")

    # Save sorted picks into a new csv file
    df_sorted.to_csv(output_file, index=False)

    print(f"File ordinato salvato come: {output_file}")


all_dfs = []

for day in range(start_day, end_day + 1):
    inputfile = os.path.join(output_picks_dir, f"picks_{year}_{day:03d}.csv")
    if os.path.exists(inputfile):
        print(f"Reading file: {inputfile}")
        df = pd.read_csv(inputfile)
        all_dfs.append(df)
    else:
        print(f"Warning: File not found for day {day}: {inputfile}")

if all_dfs:
    # Concatenate all dataframes
    combined_df = pd.concat(all_dfs, ignore_index=True)
    
    # Define output file
    outputfile = os.path.join(output_picks_dir, f"{start_day}_{end_day}_{year}_picks_sort.csv")
    
    # Run sorting and saving
    sort_seismic_picking(combined_df, outputfile)
else:
    print("No pick files found to process.")
