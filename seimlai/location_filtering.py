#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create 'location-1D.quality' from Hypoellipse 'location-1D.out'.

Output columns (order):
IPOSTRINGA LAT LON DEPTH N_P N_S RMS_HE RMS_W RMS_UW SEH SEZ GAP

Note: N_P and N_S exclude picks with weight = 3 (immediately after EP/ES).
"""
import sys, re, math
from pathlib import Path
from datetime import datetime
import os
import pandas as pd
import numpy as np

def parse_summary_line(line):
    """Support both origin formats and variable spacing in tail columns."""
    # Format A: YYYYMMDD HH MM SS.SS lat lon depth ...
    # Uses \s+ (not .*?) to reliably match single-digit hour/minute (e.g. '6 7 59.52').
    # Depth may lack a leading zero (e.g. '.68'), so pattern allows optional leading dot.
    m = re.match(
        r"\s*(\d{8})\s+(\d{1,2})\s+(\d{1,2})\s+([\d.]+)\s+"
        r"(\d{1,3})([ns])\s*([\d.]+)\s+"
        r"(\d{1,3})([ew])\s*([\d.]+)\s+"
        r"([\-]?\.?\d+(?:\.\d+)?)\s+(.*)$",
        line, flags=re.IGNORECASE
    )
    HH = MM = SSf = None
    if m:
        date, HHs, MMs, SSs, lat_deg, lat_hem, lat_min, lon_deg, lon_hem, lon_min, depth, tail = m.groups()
        HH, MM, SSf = int(HHs), int(MMs), float(SSs)
    else:
        # Format B: YYYYMMDD <optional junk, like '*'> HHMM SS.SS ...
        # HHMM is 3-4 digits (e.g. '018' = HH=0, MM=18; '1342' = HH=13, MM=42).
        # Depth may lack a leading zero (e.g. '.68').
        m = re.match(
            r"\s*(\d{8}).*?(\d{3,4})\s+([\d.]+)\s+"
            r"(\d{1,3})([ns])\s*([\d.]+)\s+"
            r"(\d{1,3})([ew])\s*([\d.]+)\s+"
            r"([\-]?\.?\d+(?:\.\d+)?)\s+(.*)$",
            line, flags=re.IGNORECASE
        )
        if not m:
            return None
        date, HHMMs, SSs, lat_deg, lat_hem, lat_min, lon_deg, lon_hem, lon_min, depth, tail = m.groups()
        HHMM = int(HHMMs)
        HH, MM = HHMM // 100, HHMM % 100
        SSf = float(SSs)

    tokens = tail.split()
    if len(tokens) < 3:
        return None
        
    try:
        rms_str = tokens[-3]
        
        rms_val = float(rms_str)
        
        if rms_val >= 10.0 and "." in rms_str:
            rms_he = float("0." + rms_str.split(".")[1])
            gap = int(tokens[-4])
        else:
            rms_he = rms_val
            gap = int(tokens[-5])
            
    except (ValueError, IndexError):
        return None

    return {
        "date": date, "HH": HH, "MM": MM, "SSf": SSf,
        "lat_deg": lat_deg, "lat_hem": lat_hem, "lat_min": lat_min,
        "lon_deg": lon_deg, "lon_hem": lon_hem, "lon_min": lon_min,
        "depth": float(depth), "gap": gap, "rms_he": rms_he,
    }

def parse_events(lines):
    events = []
    N = len(lines); i = 0
    while i < N:
        if re.search(r"\bdate\s+origin\s+lat\s+long\s+depth\b", lines[i]):
            j = i + 1
            while j < N and lines[j].strip() == "":
                j += 1
            if j >= N: break
            
            info = parse_summary_line(lines[j])
            
            if not info:
                print(f"WARNING: Event discarded. Row index: {j}. Could not parse summary line: '{lines[j].strip()}'", file=sys.stderr)
                i = j + 1
                continue
            ipostringa = f'{info["date"]}_{info["HH"]:02d}{info["MM"]:02d}{int(info["SSf"]):02d}{(info["SSf"]-int(info["SSf"])):.2f}'.replace("0.", ".")
            lat = int(info["lat_deg"]) + float(info["lat_min"]) / 60.0
            if info["lat_hem"].lower() == "s": lat = -lat
            lon = int(info["lon_deg"]) + float(info["lon_min"]) / 60.0
            if info["lon_hem"].lower() == "w": lon = -lon

            depth = info["depth"]; gap = info["gap"]; rms_he = info["rms_he"]

            seh_val = math.nan; sez_val = math.nan
            for t in range(j+1, min(j+8, N-1)):
                line2 = lines[t]
                m1 = re.search(r"seh\s*=\s*([\-0-9.]+).*sez\s*=\s*([\-0-9.]+)", line2, flags=re.IGNORECASE)
                if m1:
                    seh_val = float(m1.group(1)); sez_val = float(m1.group(2)); break
                if re.search(r"^\s*seh\s+sez\b", line2, flags=re.IGNORECASE) and (t+1) < N:
                    nums = re.findall(r"[-+]?\d+\.\d+|[-+]?\d+", lines[t+1])
                    if len(nums) >= 2:
                        seh_val = float(nums[0]); sez_val = float(nums[1]); break

            k = j + 1
            while k < N and "-- travel times and delays --" not in lines[k]:
                if re.search(r"\bdate\s+origin\s+lat\s+long\s+depth\b", lines[k]):
                    k = None; break
                k += 1

            resid_vals = []; weights = []; nP = nS = 0
            if k is not None and k < N:
                k += 1
                while k < N:
                    sline = lines[k]
                    if sline.strip() == "": break
                    if "earthquake location" in sline and re.search(r"\d{2}/\d{2}/\d{2}", sline): break

                    if " EP " in sline or sline.strip().startswith("EP ") or " ES " in sline or sline.strip().startswith("ES "):
                        mpha = re.search(r"\b(EP|ES)\b", sline)
                        if mpha:
                            pha = mpha.group(1)
                        else:
                            pha = "EP" if "EP" in sline else "ES"

                        if pha == "EP": nP += 1
                        else: nS += 1
                        mres = list(re.finditer(r"\s([+-]?\d+\.\d+)\s", " "+sline+" "))
                        resid_val = float(mres[-1].group(1)) if mres else None
                        stder_val = None
                        if mres:
                            end = mres[-1].start(1)
                            left = sline[:end]
                            mstd = list(re.finditer(r"([+-]?\d+\.\d+|-----)", left))
                            if mstd:
                                cand = mstd[-1].group(1)
                                if cand != "-----":
                                    stder_val = float(cand)
                        if resid_val is not None:
                            weights.append(1.0/(stder_val**2) if (stder_val and stder_val>0) else 1.0)
                            resid_vals.append(resid_val)

                    k += 1
                i = k if k is not None else j+1
            else:
                i = j+1

            rms_uw = math.sqrt(sum(x*x for x in resid_vals)/len(resid_vals)) if resid_vals else float("nan")
            rms_w  = math.sqrt(sum(w*(x**2) for x,w in zip(resid_vals, weights))/sum(weights)) if resid_vals else float("nan")

            events.append({
                "IPOSTRINGA": ipostringa, "LAT": lat, "LON": lon, "DEPTH": depth,
                "N_P": nP, "N_S": nS,
                "RMS_HE": rms_he, "RMS_W": rms_w, "RMS_UW": rms_uw,
                "SEH": seh_val, "SEZ": sez_val, "GAP": gap
            })
        else:
            i += 1
    return events

def main(in_file, out_file):
    try:
        lines = [ln.rstrip("\n") for ln in open(in_file, "r", errors="ignore")]
    except FileNotFoundError:
        print(f"Error: Input file '{in_file}' not found.")
        sys.exit(1)
        
    events = parse_events(lines)
    
    with open(out_file, "w") as out:
        out.write("IPOSTRINGA LAT LON DEPTH N_P N_S RMS_HE RMS_W RMS_UW SEH SEZ GAP\n")
        for ev in events:
            out.write(
                f'{ev["IPOSTRINGA"]} '
                f'{ev["LAT"]:.5f} {ev["LON"]:.5f} '
                f'{ev["DEPTH"]:.2f} '
                f'{ev["N_P"]} {ev["N_S"]} '
                f'{ev["RMS_HE"]:.4f} '
                f'{(ev["RMS_W"] if math.isfinite(ev["RMS_W"]) else -999.99):.4f} '
                f'{(ev["RMS_UW"] if math.isfinite(ev["RMS_UW"]) else -999.99):.4f} '
                f'{(ev["SEH"] if math.isfinite(ev["SEH"]) else -999.99):.2f} '
                f'{(ev["SEZ"] if math.isfinite(ev["SEZ"]) else -999.99):.2f} '
                f'{ev["GAP"]}\n'
            )
    print(f"Wrote {len(events)} events to {out_file}")


FILE_LOC = None
FILE_OUT = None
FILE_PHS = None

MAX_GAP = None
MAX_RMS = None
MAX_ERH = None
MAX_ERZ = None

WEIGHT_MAP = {
    0: 1.00,
    1: 0.75,
    2: 0.50,
    3: 0.25
}


def _apply_context(ctx):
    globals().update(ctx.legacy_globals())
    globals().update({
        "FILE_LOC": location_1d_quality_path,
        "FILE_OUT": location_1d_out_path,
        "FILE_PHS": phs_file_path,
        "MAX_GAP": DD_MAX_GAP,
        "MAX_RMS": DD_MAX_RMS,
        "MAX_ERH": DD_MAX_ERH,
        "MAX_ERZ": DD_MAX_ERZ,
    })


def read_data_file(filepath, skiprows, names_count):
    """Generic function to safely read space-delimited files."""
    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)
    
    try:
        return pd.read_csv(
            filepath, 
            sep=r'\s+', 
            header=None,
            names=range(names_count), 
            skiprows=skiprows, 
            skipinitialspace=True,
            on_bad_lines='skip'
        )
    except Exception as e:
        print(f"ERROR reading file {filepath}: {e}")
        sys.exit(1)


def generate_valid_event_ids():
    """
    Generates the original OUT event IDs that correspond to VALID events
    actually written in the location quality workflow.
    """
    print(f"3. Generating valid event IDs from {FILE_OUT}...")

    valid_ids = []
    current_out_event_id = 0

    if not os.path.exists(FILE_OUT):
        print(f"ERROR: OUT file not found: {FILE_OUT}")
        sys.exit(1)

    try:
        with open(FILE_OUT, 'r') as f:
            lines = f.readlines()
    except IOError as e:
        print(f"ERROR reading {FILE_OUT}: {e}")
        sys.exit(1)

    i = 0
    n_lines = len(lines)

    while i < n_lines:
        line = lines[i]

        if "earthquake location" in line:
            current_out_event_id += 1
            found_date_origin = False

            j = i + 1
            while j < n_lines:
                if "earthquake location" in lines[j]:
                    break

                low = lines[j].lower()
                if ("date" in low and "origin" in low and
                        "lat" in low and "long" in low):
                    found_date_origin = True
                    break
                j += 1

            if found_date_origin:
                valid_ids.append(current_out_event_id)

        i += 1

    print(f"   Found {len(valid_ids)} valid OUT event IDs.")
    return valid_ids


def read_and_filter_data():
    """Reads all input files, applies filters, matches IDs, and prepares DataFrames."""
    
    print(f"1. Reading location quality file: {FILE_LOC}")

    col_names_loc = [
        'T', 'LAT', 'LON', 'DEP', 'N_P', 'N_S', 'RMS_HYPO', 'W_RMS', 
        'UW', 'ERH', 'ERZ', 'GAP'
    ]

    df_loc_raw = read_data_file(FILE_LOC, skiprows=1, names_count=30)
        
    df_loc = df_loc_raw.iloc[:, :len(col_names_loc)]
    df_loc.columns = col_names_loc

    df_loc_filtered = df_loc[
        (df_loc['GAP'] < MAX_GAP) &
        (df_loc['RMS_HYPO'] < MAX_RMS) &
        (df_loc['ERH'] < MAX_ERH) &
        (df_loc['ERZ'] < MAX_ERZ)
    ].copy()

    all_original_ids = generate_valid_event_ids()
    len_loc = len(df_loc)
    len_ids = len(all_original_ids)
    min_len = min(len_loc, len_ids)
    
    df_id_map = pd.DataFrame({
        'Original_Key': df_loc.index[:min_len], 
        'ID': all_original_ids[:min_len] 
    })
    
    df_loc_filtered['Original_Key'] = df_loc_filtered.index
    
    df_loc_final = pd.merge(
        df_loc_filtered, 
        df_id_map,
        on='Original_Key', 
        how='inner' 
    ).drop(columns=['Original_Key'])

    df_loc_final['ID'] = df_loc_final['ID'].astype(np.int64) 
    print(f"   Successfully assigned sequential IDs to {len(df_loc_final)} filtered events.")
    print("-" * 50) 

    print(f"4. Reading phase arrivals file: {FILE_PHS}")

    try:
        with open(FILE_PHS, 'r') as f:
            lines = [line.rstrip('\n') for line in f if line.strip() and not line.strip().startswith('10')]
    except IOError as e:
        print(f"ERROR reading phase file (IOError): {e}")
        sys.exit(1) 

    data = []
    lines_processed = 0
    lines_added = 0
    
    for line in lines:
        lines_processed += 1
        
        if len(line) < 113 and len(line) < 40:
            continue

        id_str = line[107:113].strip()
        try:
            event_id = int(id_str)
        except ValueError:
            continue

        station_name_base = line[0:4].strip()
        component_char = line[77:78].strip() if len(line) >= 78 else '' 
        station_name_full = (station_name_base + component_char).ljust(5)[:5] 

        t_date_base_raw = line[8:25]
        t_date_base_num = ''.join(filter(str.isdigit, t_date_base_raw))
        t_date_base = t_date_base_num[:10]
        
        if len(t_date_base) != 10 or not t_date_base.isdigit():
             continue

        phase_p = line[4:6].strip()
        if phase_p == 'EP' and len(line) >= 25:
            w_p_char = line[7:8].strip() 
            t_p_str_raw = line[8:25].strip()
            t_p_str_raw_full = t_p_str_raw.replace(' ', '').strip()
            
            if len(t_p_str_raw_full) >= 13:
                data.append({
                    'station_name': station_name_full,
                    'phase': 'P',
                    'arrival_time_str': t_p_str_raw_full,
                    'weight_char': w_p_char,
                    'PHS_ID': event_id
                })
                lines_added += 1
            
        t_s_sec_raw = line[31:36].strip() 
        
        if t_s_sec_raw: 
            w_s_char = line[39:40].strip()
            
            if '.' in t_s_sec_raw:
                s_parts = t_s_sec_raw.split('.')
                t_s_sec = s_parts[0].zfill(2)
                t_s_dec = s_parts[1]
            else:
                t_s_sec = t_s_sec_raw.zfill(2)
                t_s_dec = ''
            
            t_s_full = t_date_base + t_s_sec + ("." + t_s_dec if t_s_dec else "")
            
            if len(t_s_full) >= 13:
                data.append({
                    'station_name': station_name_full,
                    'phase': 'S',
                    'arrival_time_str': t_s_full,
                    'weight_char': w_s_char,
                    'PHS_ID': event_id
                })
                lines_added += 1
    
    df_phs = pd.DataFrame(data)
    
    if df_phs.empty:
        df_phs_final = pd.DataFrame(columns=['station_name', 'phase', 'arrival_time_str', 'weight', 'ID'])
        print("   Total phases matched to final events: 0")
        print("-" * 40)
        return df_loc_final, df_phs_final

    df_phs['weight_int'] = pd.to_numeric(df_phs['weight_char'], errors='coerce').fillna(3).astype(np.int64)
    df_phs['weight'] = df_phs['weight_int'].replace(WEIGHT_MAP) 
    df_phs = df_phs[df_phs['weight_int'] != 4].drop(columns=['weight_int', 'weight_char']).copy()
    
    df_loc_final['PHS_ID_Match'] = df_loc_final['ID'] 
    
    df_phs_final = pd.merge(
        df_phs,
        df_loc_final[['ID', 'PHS_ID_Match']],
        left_on='PHS_ID',
        right_on='PHS_ID_Match',
        how='inner'
    ).drop(columns=['PHS_ID', 'PHS_ID_Match']).copy()
    
    print(f"   Total phases matched to final events: {len(df_phs_final)}")
    
    return df_loc_final, df_phs_final

def prepare_filtered_data(ctx):
    _apply_context(ctx)
    main(FILE_OUT, FILE_LOC)
    return read_and_filter_data()


def run(ctx):
    prepare_filtered_data(ctx)


def cli():
    from seimlai.context import build_context

    ctx = build_context("user_configuration/config.yaml")
    _apply_context(ctx)
    if len(sys.argv) >= 3:
        main(sys.argv[1], sys.argv[2])
    else:
        run(ctx)


run_location_filtering = run


if __name__ == "__main__":
    cli()
