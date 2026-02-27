#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jul 29 10:25:28 2025

@author: rossella.fonzetti
"""


import pandas as pd

## SORT PICKING ##
def sort_seismic_picking(input_file, output_file):
    # Read picks file
    df = pd.read_csv(input_file)

    # Rename columns
    df = df.rename(columns={
        "id": "Station",
        "timestamp": "Datetime",
        "prob": "Probability",
        "type": "Wave_Type"
    })

    # Convert Datatime column
    df["Datetime"] = pd.to_datetime(df["Datetime"])

    # Giulian Name computation (1-366)
    df["Julian_Day"] = df["Datetime"].dt.dayofyear

    # Rename Columns
    column_order = ["Julian_Day", "Station", "Datetime", "Probability", "Wave_Type"]
    df = df[column_order]

    # Sort picks
    df_sorted = df.sort_values(by="Datetime")

    # Save sorted picks into a new csv file
    df_sorted.to_csv(output_file, index=False)

    print(f"File ordinato salvato come: {output_file}")

## Parameters
dayini = "304"
dayfin = "304"
year = "2016"
base_dir = "/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/NEW_GAMMA_CONFIGURATION/2016_2017_SEQUENCE/output/output_picks"

inputfile = f"{base_dir}/picks_{year}_{dayini}.csv"
outputfile = f"{base_dir}/{dayini}_{dayfin}_{year}_picks_sort.csv"

sort_seismic_picking(inputfile, outputfile)
