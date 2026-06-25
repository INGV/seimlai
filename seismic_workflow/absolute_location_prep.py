#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Feb 16 11:16:16 2026

@author: rossella.fonzetti
"""

import pandas as pd
import os
from seismic_workflow.context import ensure_initial_directories

########################################################################
# This script filters the best location of the GaMMA seismic catalog, 
# selecting the seismic events with at least a min P and min S.
# After the filtering, the files for Hypoellipse absolute location are provided.
########################################################################

def _apply_context(ctx):
    globals().update(ctx.legacy_globals())


def _load_filtered_inputs():
    # --- Derived paths from runtime context ---
    os.makedirs(h71_filtered_dir, exist_ok=True)

    # FILE PATHS (derived from config variables)
    filecat = os.path.join(output_dir, f"seismic_catalog_with_latlon_{year}_{start_day}_{end_day}.csv")
    filepic = os.path.join(output_dir, f"gamma_pick_grouped_{year}_{start_day}_{end_day}.csv")

    # LETTURA FILE
    df_catalogo = pd.read_csv(filecat)
    df_picks = pd.read_csv(filepic)

    # SORT CATALOGO
    df_catalogo['time'] = pd.to_datetime(df_catalogo['time'])
    df_catalogo = df_catalogo.sort_values('time')

    # SORT PICKS E ASSOCIAZIONE ORIGIN TIME
    df_picks['timestamp'] = pd.to_datetime(df_picks['timestamp'])
    df_event_time = df_catalogo[['event_index', 'time']].copy()
    df_event_time.columns = ['event_idx', 'origin_time']
    df_picks = df_picks.merge(df_event_time, on='event_idx', how='left')
    df_picks = df_picks.sort_values(['origin_time', 'timestamp']).reset_index(drop=True)

    # ANALISI P e S
    df_picks['type'] = df_picks['type'].str.lower()
    grouped = df_picks.groupby(['event_idx', 'type']).size().unstack(fill_value=0)
    grouped.columns.name = None
    grouped = grouped.rename(columns={'p': 'num_p', 's': 'num_s'})

    # FILTRAGGIO EVENTI
    eventi_validi = grouped[(grouped['num_p'] >= h71_min_p) & (grouped['num_s'] >= h71_min_s)].copy()
    print(f"Number of filtered event: {len(eventi_validi)} on {df_picks['event_idx'].nunique()}")

    # ESTRAZIONE PICKS VALIDI
    df_picks_filtrati = df_picks[df_picks['event_idx'].isin(eventi_validi.index)]
    df_picks_filtrati = df_picks_filtrati.merge(eventi_validi, left_on='event_idx', right_index=True)
    return df_catalogo, df_picks_filtrati

# --- FUNZIONI DI FORMATTAZIONE E SCRITTURA ---

def format_time(time_str):
    dt = pd.to_datetime(time_str)
    year = dt.strftime('%y')
    month = dt.strftime('%m')
    day = dt.strftime('%d')
    hour = dt.strftime('%H')
    minute = dt.strftime('%M')
    sec = dt.strftime('%S.%f')[:5]
    if sec.startswith('0'):
        sec = sec[1:]
    return year, month, day, hour, minute, sec

def write_phs(df_picks_filtrati, df_catalogo, filtered_dir, filename="out.phs"):
    output_file = os.path.join(filtered_dir, filename)

    # --- Associate origin time and filtered picking ---
    df_picks_filtrati = df_picks_filtrati.copy()
    df_picks_filtrati["origin_time"] = df_picks_filtrati["event_idx"].map(
        df_catalogo.set_index("event_index")["time"]
    )

    # Sort
    df_picks_filtrati = df_picks_filtrati.sort_values(["origin_time", "timestamp"])

    with open(output_file, 'w') as f:
        for event_id, group in df_picks_filtrati.groupby('event_idx', sort=False):
            group = group.sort_values("timestamp")
            
            # Ordina le stazioni, poi i pick per stazione
            for station, station_df in group.groupby('id', sort=False):
                station_df = station_df.sort_values("timestamp")
                row = [' '] * 112

                # --- NOME STAZIONE ---
                station_name = str(station).strip()
                station_4ch = station_name[:4].rjust(4)
                for i, ch in enumerate(station_4ch):
                    row[i] = ch
                if len(station_name) > 4:
                    row[77] = station_name[4]

                p_row = station_df[station_df['type'].str.lower() == 'p']
                s_row = station_df[station_df['type'].str.lower() == 's']

                # --- GESTIONE FASE P (Reale o Fittizia) ---
                if not p_row.empty:
                    p_time = p_row.iloc[0]['timestamp']
                    prob_p = float(p_row.iloc[0]['prob'])
                    is_fittizia = False
                elif not s_row.empty:
                    # Crea P fittizia 5 secondi prima della S
                    s_time = pd.to_datetime(s_row.iloc[0]['timestamp']) 
                    p_time = (s_time - pd.Timedelta(seconds=5)).isoformat()
                    prob_p = -9.999999
                    is_fittizia = True
                else:
                    p_time = None
                    prob_p = -9.999999
                    is_fittizia = True

                if p_time is not None:
                    p_dt = pd.to_datetime(p_time)
                    row[4:6] = list("EP")
                    row[7] = '0'
                    y, mo, d, h, mi, s = format_time(p_time)
                    row[9:11]  = list(y)
                    row[11:13] = list(mo)
                    row[13:15] = list(d)
                    row[15:17] = list(h)
                    row[17:19] = list(mi)
                    sec = f"{float(s):5.2f}".rjust(5)
                    row[19:24] = list(sec)
                    if is_fittizia:
                        row[81:89] = list(f"{-9.999999:8.6f}")
                    else:
                        row[82:90] = list(f"{prob_p:8.6f}")
                else:
                    p_dt = None
                    row[81:89] = list(f"{-9.999999:8.6f}")

                # --- GESTIONE FASE S (MODIFICA QUI) ---
                if not s_row.empty:
                    row[36:38] = list("ES")
                    s_dt = pd.to_datetime(s_row.iloc[0]['timestamp'])
                    
                    if p_dt is not None:
                        # --- CORREZIONE CALCOLO SECONDI S ---
                        # Prendiamo l'inizio del minuto della P (che è quello scritto nel file)
                        # e calcoliamo la differenza totale in secondi.
                        # Questo gestisce correttamente il passaggio di minuto (es. P:59s -> S:01s diventa S:61s)
                        p_min_start = p_dt.replace(second=0, microsecond=0)
                        diff = s_dt - p_min_start
                        s_sec_value = diff.total_seconds()
                    else:
                        # Fallback nel caso remoto in cui non esista una P (nemmeno fittizia)
                        s_sec_value = s_dt.second + s_dt.microsecond / 1e6
                        
                    s_sec_str = f"{s_sec_value:5.2f}".rjust(5)
                    row[31:36] = list(s_sec_str)
                    row[39] = '0'
                    prob_s = float(s_row.iloc[0]['prob'])
                    row[92:100] = list(f"{prob_s:8.6f}")
                else:
                    row[91:99] = list(f"{-9.999999:8.6f}")

                row[106:112] = list(str(event_id).rjust(6))
                f.write(''.join(row) + '\n')

            sep = [' '] * 112
            sep[17:19] = list("10")
            f.write(''.join(sep) + '\n')


def format_hypo71_coords(value, is_lat=True):
    degrees = int(abs(value))
    minutes = (abs(value) - degrees) * 60
    hemi = 'N' if is_lat and value >= 0 else 'S' if is_lat else 'E' if value >= 0 else 'W'
    min_str = f"{minutes:.2f}".rjust(5) if minutes < 10 else f"{minutes:05.2f}"
    return f"{degrees}{hemi}{min_str}"

def write_h71_file(df_catalogo, df_picks_filtrati, output_path):
    event_ids = df_picks_filtrati['event_idx'].unique()
    
    # Sort catalog using origin time
    df_filt = df_catalogo[df_catalogo['event_index'].isin(event_ids)].copy()
    df_filt["time"] = pd.to_datetime(df_filt["time"])
    df_filt = df_filt.sort_values("time")

    with open(output_path, "w") as f:
        row = [' '] * 60
        num_eventi = f"{len(df_filt):>10}"[:10]
        row[9:18] = list(num_eventi)
        f.write("".join(row) + "\n") 

        for _, ev in df_filt.iterrows():
            row = [' '] * 60

            dt = pd.to_datetime(ev["time"])
            date_str = dt.strftime("%y%m%d")
            time_str = dt.strftime("%H%M")
            sec_str = f"{dt.second + dt.microsecond/1e6:5.2f}".rjust(5)

            lat_str = format_hypo71_coords(float(ev["latitude"]), is_lat=True).ljust(8)
            lon_str = format_hypo71_coords(float(ev["longitude"]), is_lat=False).ljust(8)

            mag_str = f"{float(ev['magnitude']):5.2f}".rjust(6)
            depth_val = f"{float(ev['z(km)']):.2f}"
            depth_float = float(ev['z(km)'])

            eid_str = str(int(ev["event_index"])).rjust(6)

            row[0:6]    = list(date_str)
            row[7:11]   = list(time_str)
            row[12:17]  = list(sec_str)
            row[18:26]  = list(lat_str)
            row[28:36]  = list(lon_str)

            if depth_float < 10:
                depth_pos = 39
            elif depth_float < 100:
                depth_pos = 38
            else:
                depth_pos = 37
            row[depth_pos:43] = list(depth_val.rjust(43 - depth_pos))

            row[46:50]  = list(mag_str)
            row[52:58]  = list(eid_str)

            f.write("".join(row) + "\n")

# --- CONVERSIONE PESI E RENAME ID ---

def prob_to_weight(prob_str):
    try:
        val = float(prob_str)
        # Probabilità not defined per P fittizie
        if val == -9.999999: 
            return '4'
        if val >= 0.95:
            return '0'
        elif val >= 0.80:
            return '1'
        elif val >= 0.60:
            return '2'
        else:
            return '3'
    except:
        return ''

def converti_phs_file(file_input, file_output, debug=False):
    event_id = 1

    with open(file_input, 'r') as fin, open(file_output, 'w') as fout:
        for idx, linea in enumerate(fin):
            original = linea.rstrip('\n')

            if original.strip() == '':
                fout.write('\n')
                continue

            is_separator = original.strip().startswith("10") or original[0:10].strip() == ''
            line = original.ljust(113)
            linea_out = list(line)

            fase_p = line[4:6]
            fase_s = line[36:38]
            tempo_p = line[9:24].strip()
            tempo_s = line[31:36].strip()
            
            prob_p_full = line[81:90].strip()
            if prob_p_full.startswith('-9'): 
                prob_p = "-9.999999"
            else: 
                prob_p = line[82:90].strip()

            prob_s = line[92:100].strip()

            peso_p = prob_to_weight(prob_p) if tempo_p != '' else ''
            peso_s = prob_to_weight(prob_s) if tempo_s != '' else ''

            if fase_p == 'EP' and peso_p != '':
                linea_out[7] = peso_p
            if fase_s == 'ES' and peso_s != '':
                linea_out[39] = peso_s

            if not is_separator:
                id_str = f"{event_id:6d}"
                linea_out[107:113] = list(id_str)
            else:
                event_id += 1 

            if debug and idx < 10: # Limito il debug alle prime righe per pulizia
                print(f"[DEBUG] Line {idx:03d} | P={prob_p} -> {peso_p} | S={prob_s} -> {peso_s}")

            fout.write(''.join(linea_out).rstrip() + '\n')

def convert_h71_ids(input_path):
    with open(input_path, "r") as f:
        lines = f.readlines()

    header = lines[0]
    body_lines = lines[1:]

    output_lines = [header]
    id_map = {}
    new_id = 1

    for line in body_lines:
        row = list(line.rstrip('\n'))
        original_id = "".join(row[52:58]).strip()

        if original_id not in id_map:
            id_map[original_id] = str(new_id).rjust(6)
            new_id += 1

        row[52:58] = list(id_map[original_id])
        output_lines.append("".join(row) + "\n")

    output_path = input_path.replace(".h71", "_conv.h71")
    with open(output_path, "w") as f_out:
        f_out.writelines(output_lines)

    print(f"File H71 update saved in: {output_path}")

def dec_to_degmin(dec_deg, is_lat=True):
    """
    Convert decimal degrees to degrees + minutes format.
    Example: 42.8295 -> '42N49.77'
    """
    degrees = int(dec_deg)
    minutes = abs(dec_deg - degrees) * 60
    direction = ('N' if dec_deg >= 0 else 'S') if is_lat else ('E' if dec_deg >= 0 else 'W')
    return f"{abs(degrees):02d}{direction}{minutes:05.2f}"


def convert_station_file_for_hypoellipse():
    df = pd.read_csv(os.path.join(case_study_dir, station_file_name))

    os.makedirs(h71_filtered_dir, exist_ok=True)

    lines = []

    for _, row in df.iterrows():
        code_full = str(row["station"])
        code_len = len(code_full)
        code = code_full[:5]

        lat = dec_to_degmin(row["latitude"], is_lat=True)
        lon = dec_to_degmin(row["longitude"], is_lat=False)
        elev = int(round(row["elevation"]))
        depth = 0
        weight = 1.00

        elev_str = f"{elev:>5}"

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

    output_path = os.path.join(h71_filtered_dir, "all.he")
    with open(output_path, "w") as f:
        for line in lines:
            f.write(line + "\n")

    os.makedirs(dd_dir, exist_ok=True)
    print(f"Station file saved in: {output_path}")


def run(ctx):
    ensure_initial_directories(ctx)
    _apply_context(ctx)
    df_catalogo, df_picks_filtrati = _load_filtered_inputs()

    # ESECUZIONE CREAZIONE FILE PHS
    write_phs(df_picks_filtrati, df_catalogo, h71_filtered_dir)

    # --- CREAZIONE FILE H71 ---
    output_h71 = os.path.join(h71_filtered_dir, "out.h71")
    write_h71_file(df_catalogo, df_picks_filtrati, output_h71)

    phs_input = os.path.join(h71_filtered_dir, "out.phs")
    phs_output = os.path.join(h71_filtered_dir, "out_conv.phs")
    converti_phs_file(phs_input, phs_output, debug=False)

    # --- CONVERSIONE ID SU FILE H71 ---
    convert_h71_ids(os.path.join(h71_filtered_dir, "out.h71"))
    convert_station_file_for_hypoellipse()


def main():
    from seismic_workflow.context import build_context

    run(build_context("config.yaml"))


run_absolute_location_prep = run


if __name__ == "__main__":
    main()
