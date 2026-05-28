#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Prepare HypoDD input files from filtered absolute locations.
"""

from datetime import datetime
import os
import sys

import pandas as pd
from config import (filtered_locations_csv_path, filtered_phases_csv_path,
                    stations_csv_path, dd_output_file, dd_station_file)

FILTERED_LOCATIONS_FILE = filtered_locations_csv_path
FILTERED_PHASES_FILE = filtered_phases_csv_path
STATIONS_FILE = stations_csv_path
OUTPUT_FILE = dd_output_file
STATION_FILE = dd_station_file


def parse_origin_time(t_str):
    """
    Converts a time string (e.g., 20161030000037.87) into a datetime object, 
    decimal seconds, and epoch time.
    """
    t_str = str(t_str).strip()
    
    if '.' in t_str:
        parts = t_str.split('.')
        date_part = parts[0]
        sec_decimal_part = parts[1]
    else:
        date_part = t_str
        sec_decimal_part = '0'
        
    if len(date_part) >= 14:
        date_part = date_part[:14]
    else:
        return None, None, None 

    try:
        dt = datetime.strptime(date_part, '%Y%m%d%H%M%S')
        sec_decimal = float("0." + sec_decimal_part)
        epoch_sec = dt.timestamp() + sec_decimal
        
        return dt, sec_decimal, epoch_sec
    except ValueError:
        return None, None, None


def read_filtered_data():
    if not os.path.exists(FILTERED_LOCATIONS_FILE):
        print(f"ERROR: Filtered locations file not found: {FILTERED_LOCATIONS_FILE}")
        print("Run 07_locations_filtering.py before relative relocation.")
        sys.exit(1)

    if not os.path.exists(FILTERED_PHASES_FILE):
        print(f"ERROR: Filtered phases file not found: {FILTERED_PHASES_FILE}")
        print("Run 07_locations_filtering.py before relative relocation.")
        sys.exit(1)

    df_loc_final = pd.read_csv(FILTERED_LOCATIONS_FILE)
    df_phs_final = pd.read_csv(FILTERED_PHASES_FILE)

    if 'ID' in df_loc_final.columns:
        df_loc_final['ID'] = df_loc_final['ID'].astype(int)
    if 'ID' in df_phs_final.columns and not df_phs_final.empty:
        df_phs_final['ID'] = df_phs_final['ID'].astype(int)

    return df_loc_final, df_phs_final


def create_hypodd_combined_file(df_loc_final, df_phs_final):
    """
    Generates the hypoDD combined input file, calculating travel times.
    """
    print(f"5. Starting generation of combined output file: {OUTPUT_FILE}")

    origin_times = {}
    for index, row in df_loc_final.iterrows():
        t_full_str = str(row['T']).replace('_', '') 
        
        dt, ot_sec_dec, ot_epoch = parse_origin_time(t_full_str)
        
        if dt and ot_epoch:
            origin_times[row['ID']] = (dt, ot_sec_dec, ot_epoch)

    def parse_phase_time(t_str):
        t_str = str(t_str).strip()
        if len(t_str) < 13: 
            return None, None, None

        date_part = t_str[:10]
        sec_part_raw = t_str[10:]
        
        if '.' in sec_part_raw:
            parts = sec_part_raw.split('.')
            sec_part = parts[0].zfill(2)
            sec_decimal_part = parts[1]
        else:
            sec_part = sec_part_raw.zfill(2)
            sec_decimal_part = '0'
        
        try:
            sec_float = float(sec_part) + float("0." + sec_decimal_part)
            dt_base = datetime.strptime(date_part, '%y%m%d%H%M')
            dt_full_arrival = dt_base + pd.Timedelta(seconds=sec_float)
            epoch_sec = dt_full_arrival.timestamp()

            return dt_full_arrival, sec_float, epoch_sec
            
        except ValueError:
            return None, None, None

    if df_phs_final.empty:
        df_phs_final_processed = df_phs_final
    else:
        df_phs_final_processed = df_phs_final.copy()
        
        df_phs_final_processed[['dt_arr', 'arr_sec_float', 'arrival_epoch']] = df_phs_final_processed['arrival_time_str'].apply(
            lambda x: pd.Series(parse_phase_time(x))
        )
        df_phs_final_processed = df_phs_final_processed.dropna(subset=['arrival_epoch']).copy()

    try:
        with open(OUTPUT_FILE, 'w') as f:
            df_loc_sorted = df_loc_final.sort_values(by='ID')
            
            for index, event in df_loc_sorted.iterrows():
                event_id = event['ID']
                ot_data = origin_times.get(event_id)
                if ot_data is None:
                    continue 

                ot_dt, ot_sec_dec, ot_epoch = ot_data
                
                ot_sec_float = ot_dt.second + ot_sec_dec
                
                event_line = (
                    f"# {ot_dt.year:<4} {ot_dt.month:>2} {ot_dt.day:>2} {ot_dt.hour:>2} "
                    f"{ot_dt.minute:>2} {ot_sec_float:>6.2f} "
                    f"{event['LAT']:>10.5f} {event['LON']:>10.5f} {event['DEP']:>8.4f} "
                    f"0.00000 0.00000 0.00000 0.00000 "
                    f"{event_id:>4}"
                )
                f.write(event_line + "\n")
                
                if not df_phs_final_processed.empty:
                    event_phases = df_phs_final_processed[df_phs_final_processed['ID'] == event_id].copy() 
                    
                    if not event_phases.empty:
                        event_phases['travel_time'] = event_phases['arrival_epoch'] - ot_epoch
                        
                        for i, phase in event_phases.iterrows():
                            phase_line = (
                                f"{phase['station_name']:<5} {phase['travel_time']:>6.3f} "
                                f"{phase['weight']:>6.3f} {phase['phase']}"
                            )
                            f.write(phase_line + "\n")
                    
        print(f"File '{OUTPUT_FILE}' created successfully.")
        
    except IOError as e:
        print(f"Error writing file: {e}")


def create_station_file():
    """
    Reads station data from the CSV and generates the station.dat file
    formatted as: STATION_NAME LAT LON Z (quota in metri senza decimali).
    """
    print(f"6. Starting generation of station file: {STATION_FILE}")
    
    try:
        df_stations = pd.read_csv(
            STATIONS_FILE, 
            usecols=['station', 'latitude', 'longitude', 'elevation']
        )
        
        df_stations.columns = ['NAME', 'LAT', 'LON', 'Z']
        df_stations = df_stations.dropna().drop_duplicates(subset=['NAME'])
        
    except FileNotFoundError:
        print(f"ERROR: Stations file not found at {STATIONS_FILE}. Skipping station.dat generation.")
        return
    except KeyError as e:
        print(f"ERROR: Column {e} not found in stations.csv. Check column names.")
        return
    
    try:
        with open(STATION_FILE, 'w') as f:
            for index, row in df_stations.iterrows():
                station_line = (
                    f"{row['NAME']:<6} "
                    f"{row['LAT']:>10.6f} "
                    f"{row['LON']:>10.6f} "
                    f"{row['Z']:>10.0f}"
                )
                f.write(station_line + "\n")
                
        print(f"File '{STATION_FILE}' created successfully with {len(df_stations)} stations.")
        
    except IOError as e:
        print(f"Error writing station file: {e}")


if __name__ == '__main__':
    df_loc_final, df_phs_final = read_filtered_data()
    
    if not df_loc_final.empty:
        create_hypodd_combined_file(df_loc_final, df_phs_final)
    else:
        print("No events passed the quality filters or could be matched. Output file not generated.")
        
    create_station_file()
