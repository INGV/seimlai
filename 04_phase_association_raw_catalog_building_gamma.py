#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jul 29 09:10:01 2025

@author: rossella.fonzetti
"""

#################################################################################
# This script uses GaMMA associator (Zhu et al., 2022) to associate picks to a single event
# A raw seismic catalog  and associated picks file will be provided.
################################################################################

#import libraries
import os
from config import *

# Set GMT library path before importing pygmt
if GMT_LIBRARY_PATH:
    os.environ["GMT_LIBRARY_PATH"] = GMT_LIBRARY_PATH

import obspy
from obspy.clients.fdsn import Client
from obspy import UTCDateTime
from obspy.core.utcdatetime import UTCDateTime
from obspy.signal.filter import bandpass
from obspy.geodetics import gps2dist_azimuth
from pyproj import CRS, Transformer
import pandas as pd
import numpy as np
from collections import Counter
from tqdm import tqdm
import matplotlib.pyplot as plt
import seaborn as sns
import torch
import warnings
from gamma.utils import association
import pygmt

sns.set(font_scale=1.2)
sns.set_style("ticks")


if __name__ == "__main__":
    # Define output directory
    os.makedirs(output_dir, exist_ok=True)

    #FUNCTIONS TO READ STATION FILE AND CONVERT COORDINATES
    def process_stations(file_path):
        stations_df = pd.read_csv(file_path)
        
        # Coordinate Conversion in UTM 33N
        stations_df["x(km)"], stations_df["y(km)"] = zip(
            *stations_df.apply(lambda row: transformer.transform(row["longitude"], row["latitude"]), axis=1)
        )
        # km conversion
        stations_df["x(km)"] /= 1e3
        stations_df["y(km)"] /= 1e3  
    
        return stations_df
    
    
    # UPLOAD PICKS FILE
    sorted_file = os.path.join(output_picks_dir, f"{start_day}_{end_day}_{year}_picks_sort.csv")
    picks_df = pd.read_csv(sorted_file, sep=",", parse_dates=["Datetime"])
    if "Amp" not in picks_df.columns and "Amplitude" in picks_df.columns:
        picks_df = picks_df.rename(columns={"Amplitude": "Amp"})
    # Estract nework and station name
    # Extract station name from dot-notation if present (e.g. "IV.INTR." -> "INTR")
    # If names are already clean (e.g. "ED01"), leave them as-is
    if picks_df["Station"].str.contains(r"\.").any():
        #picks_df["Network"] = picks_df["Station"].str.split(".").str[0]
        picks_df["Station"] = picks_df["Station"].str.split(".").str[-2]
    
    # Change network and station columns position
    picks_df = picks_df[["Julian_Day", "Station", "Datetime", "Probability", "Amp","Wave_Type"]]
    
    # Dataframe creation
    pick_df = []
    for _, row in picks_df.iterrows():
        pick_df.append({
            "id": row['Station'], #Station Name
            "timestamp": row["Datetime"], # Arrival time
            "prob": row["Probability"],  # PhaseNet probability
            "amp": row["Amp"],  #phase amplitude
            "type": row["Wave_Type"].lower() # waves type (p or s)
        })
    pick_df = pd.DataFrame(pick_df)
    
    #UPLOAD STATIONS FILE
    stations_df = process_stations(os.path.join(case_study_dir, "stations.csv"))
    stations_df["elevation"] = pd.to_numeric(stations_df["elevation"], errors="coerce")
    
    station_df = pd.DataFrame({
        "id": stations_df["station"],
        "longitude": stations_df["longitude"],
        "latitude": stations_df["latitude"],
        "elevation(m)": stations_df["elevation"],
        "x(km)": stations_df["x(km)"],
        "y(km)": stations_df["y(km)"],
        "z(km)": -stations_df["elevation"] / 1000  
    })
    
    #RUN GaMMA ASSOCIATOR
    os.environ["PYTHONWARNINGS"] = "ignore"
    warnings.filterwarnings("ignore")
    
    # Ensure both id columns are strings to prevent merge errors in GaMMA
    pick_df["id"] = pick_df["id"].astype(str)
    station_df["id"] = station_df["id"].astype(str)
    
    catalogs, assignments = association(pick_df, station_df, config, method=config["method"])
    catalog = pd.DataFrame(catalogs)
    if catalog.empty:
        print("ERROR: GaMMA association returned 0 events!")
        print(f"  Input picks: {len(pick_df)}")
        matched = pick_df["id"].isin(station_df["id"]).sum()
        print(f"  Picks matching a station: {matched}/{len(pick_df)}")
        print("  Check that pick station IDs match station_df IDs.")
        raise SystemExit(1)
    assignments = pd.DataFrame(assignments, columns=["pick_idx", "event_idx", "prob_gamma"])
    
    # SAVE Raw CATALOG with km coordinates
    catalog_file_in=os.path.join(output_dir,f"seismic_catalog_{year}_{start_day}_{end_day}.csv")
    catalog.to_csv(catalog_file_in, index=False)
    
    # Save picks 
    assignments["pick_idx"] = assignments["pick_idx"].astype(int)
    assignments["event_idx"] = assignments["event_idx"].astype(int)   
    if pick_df.index.dtype != 'int64':
        pick_df = pick_df.reset_index()   
    missing_picks = set(pick_df.index) - set(assignments["pick_idx"])
    if missing_picks:
        print(f"Warning {len(missing_picks)} pick_idx not find in assignments!")  
    picks_with_events = pick_df.merge(assignments, left_index=True, right_on="pick_idx", how="left")
    picks_with_events["event_idx"] = picks_with_events["event_idx"].fillna(-1).astype(int)  
    picks_with_events = picks_with_events.merge(catalog, left_on="event_idx", right_on="event_index", how="left") 
    missing_events = set(picks_with_events["event_idx"]) - set(catalog["event_index"])
    if missing_events:
        print(f"Warning: {len(missing_events)} event_idx not match into the catalog!")
    picks_with_events.drop(columns=["event_index"], inplace=True, errors="ignore")
    picks_with_events = picks_with_events[["id", "timestamp", "prob", "amp", "type", "event_idx", "prob_gamma"]]
    # Save all picks (the id .-1 is referred to un-associated picks)
    output_gamma_picks = os.path.join(output_dir, f"gamma_pick_{year}_{start_day}_{end_day}.csv")
    picks_with_events.to_csv(output_gamma_picks, index=False)
    
    print(f"Picks save in {output_gamma_picks}!")
    
    # --------------------------------------
    # Save only associated picks
    gamma_picks = picks_with_events.copy()
    associated_picks = gamma_picks[gamma_picks["event_idx"] != -1].copy()
    associated_picks = associated_picks.sort_values(by=["event_idx", "timestamp"])
    output_associated_picks = os.path.join(output_dir, f"gamma_pick_grouped_{year}_{start_day}_{end_day}.csv")
    associated_picks.to_csv(output_associated_picks, index=False)
    
    print(f"Associated picks saved in {output_associated_picks}!")
    
    #CONVERT FROM km to ° COORDINATES 
    transformer_inv = Transformer.from_crs(utm33n, wgs84, always_xy=True) 
    x_col = "x(km)" if "x(km)" in catalog.columns else "x"
    y_col = "y(km)" if "y(km)" in catalog.columns else "y"
    lon_lat = [transformer_inv.transform(x * 1e3, y * 1e3) for x, y in zip(catalog[x_col], catalog[y_col])]
    catalog["longitude"] = [coord[0] for coord in lon_lat]
    catalog["latitude"] = [coord[1] for coord in lon_lat]
    
    # Delate km coordinate from dataframe and put the degree coordinate.
    catalog = catalog.drop(columns=[x_col, y_col])
    catalog_file=os.path.join(output_dir,f"seismic_catalog_with_latlon_{year}_{start_day}_{end_day}.csv")
    #Save catalog with correct coordinates
    catalog.to_csv(catalog_file, index=False)
    print("Seismic catalog saved in seismic_catalog_with_latlon.csv con solo longitude e latitude.")
    
    # Use PyGMT to plot the seismicity
    pygmt.config(GMT_VERBOSE="q")
    # 1. Central Italy range
    region = [12.5, 14.00, 42.00, 43.50]
    
    # 2. Figure
    fig = pygmt.Figure()
    
    # 3. Topography Colormap 
    pygmt.makecpt(cmap="gray", series=[-1000, 3000,1], truncate="0.4/1.0",continuous=True)
    
    # 4. Topography with realistic shading
    fig.grdimage(
        grid=GMT_GRID_PATH,  # your grd file or @
        region=region,
        projection="M6i",
        shading="+a135+nt0.6",
        cmap=True,
        frame=["af", '+t"Central Italy - 2016/10/30 Seismicity"']
    )
    
    # 5. Coastlines 
    fig.coast(shorelines="1/0.25p,black", resolution="h")
    
    # 6. Depth colormap (continuous viridis)
    pygmt.makecpt(
        cmap="viridis",
        series=[catalog["z(km)"].min(), catalog["z(km)"].max(),1],
        continuous=True
    )
    
    # 7. Plot earthquakes (viridis, no black outline)
    fig.plot(
        x=catalog["longitude"],
        y=catalog["latitude"],
        style="c0.06c",
        fill=catalog["z(km)"],
        cmap=True,
        pen=False,            
        transparency=20
    )
    
    # 8. Seismic stations
    fig.plot(
        x=station_df["longitude"],
        y=station_df["latitude"],
        style="t0.25c",
        fill="red",
        pen="black"
    )
    
    # 9. Depth colorbar (below the map)
    fig.colorbar(
        position="JBC+o2.0c/1.4c+w8c/0.4c+h",  # bottom center, offset vertical -1.4c
        frame='af+l"Depth (km)"'
    )
    
    # 10. Topography colorbar (top right) — [commented out]
    #fig.colorbar(
    #    position="JTR+o-1.8c/0c+w0.3c/3c+v",  # verticale
    #    frame='af+l"Elevation (m)"'
    #)
    
    # 11. Scale bar (50 km, bottom left)
    fig.basemap(map_scale="jBL+o0.3c/-1.5c+w10k+f+l")
    
    # 12. Inset map of Italy centered on the Apennines
    with fig.inset(position="jTR+w3.5c+o0.3c", box="+gwhite+p1p,black"):
        fig.coast(
            region=[8, 17, 40.5, 47],
            projection="M3.5c",
            land="gray85",
            water="white",
            shorelines="0.25p,black"
        )
        rect = [
            [region[0], region[2]],
            [region[1], region[2]],
            [region[1], region[3]],
            [region[0], region[3]],
            [region[0], region[2]],
        ]
        fig.plot(data=rect, pen="1p,red")
    
    # Save plot 
    output_file = os.path.join(output_dir, f"catalog_{year}_{start_day}_{end_day}.pdf")
    fig.savefig(output_file, dpi=300)
    
    # Show the plot
    fig.show()
