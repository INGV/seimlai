#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Created on Tue Nov 11 14:39:43 2025

@author: rossella.fonzetti
"""
from datetime import datetime
import pandas as pd
import numpy as np
import sys
import os
from config import (THR, location_1d_quality_path, location_1d_out_path,
                    phs_file_path, stations_csv_path, dd_output_file,
                    dd_station_file, DD_MAX_GAP, DD_MAX_RMS, DD_MAX_ERH, DD_MAX_ERZ)

# --- 1. Configuration (from config.py) ---
FILE_LOC = location_1d_quality_path
FILE_OUT = location_1d_out_path
FILE_PHS = phs_file_path
STATIONS_FILE = stations_csv_path
OUTPUT_FILE = dd_output_file
STATION_FILE = dd_station_file

# Filtering criteria
MAX_GAP = DD_MAX_GAP
MAX_RMS = DD_MAX_RMS
MAX_ERH = DD_MAX_ERH
MAX_ERZ = DD_MAX_ERZ

# Mappatura dei pesi richiesta per l'output di hypoDD
WEIGHT_MAP = {
    0: 1.00,
    1: 0.75,
    2: 0.50,
    3: 0.25
}

# --- 2. Helper Functions ---

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


def read_data_file(filepath, skiprows, names_count):
    """Generic function to safely read space-delimited files."""
    if not os.path.exists(filepath):
        print(f"ERROR: File not found: {filepath}")
        sys.exit(1)
    
    try:
        # Uso sep='\s+' per risolvere FutureWarning
        return pd.read_csv(
            filepath, 
            sep='\s+', 
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

    Important:
    FILE_OUT may contain extra 'earthquake location' blocks that are failed
    attempts (for example blocks with NaN / IEEE_INVALID_FLAG and no
    'date origin ...' summary). Those blocks are counted by a naive grep but
    do NOT correspond to rows in FILE_LOC. If we assign IDs by counting every
    'earthquake location', the IDs drift after the first failed block.

    This function counts every 'earthquake location' as an original OUT event
    number, but only keeps the ones that also contain a 'date origin ...'
    header before the next earthquake block.
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


# --- 3. Read phs file anche match the ID---

def read_and_filter_data():
    """Reads all input files, applies filters, matches IDs, and prepares DataFrames."""
    
    # --- A. Read and Filter Location File (.quality) ---
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

    # --- Generazione e Assegnazione ID ---
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


    # --- B. Read and Clean Phase File (.phs) - LOGICA FINALE CORRETTA ---
    print(f"4. Reading phase arrivals file: {FILE_PHS} (CORREZIONE TEMPO S ULTIMA CHANCE)")

    
    # 1. Legge il file riga per riga come testo
    try:
        with open(FILE_PHS, 'r') as f:
            lines = [line.rstrip('\n') for line in f if line.strip() and not line.strip().startswith('10')]
    except IOError as e:
        print(f"ERROR reading phase file (IOError): {e}")
        sys.exit(1) 

    data = []
    lines_processed = 0
    lines_added = 0
    
    # 2. Estrae i campi critici usando lo slicing stringa (posizione fissa)
    for line in lines:
        lines_processed += 1
        
        # Saltiamo le righe troppo corte
        if len(line) < 113 and len(line) < 40: continue

        # --- Estrazione ID Evento ---
        id_str = line[107:113].strip()
        try:
            event_id = int(id_str)
        except ValueError:
            continue

        # --- Estrazione Nome Stazione (4 caratteri + 5° carattere opzionale in pos 78) ---
        station_name_base = line[0:4].strip()
        component_char = line[77:78].strip() if len(line) >= 78 else '' 
        station_name_full = (station_name_base + component_char).ljust(5)[:5] 

        
        # --- Tempo Base YYMMDDHHMM (per P e S) ---
        # Prendiamo una porzione PIÙ LUNGA [8:25] (coprendo anche i secondi P e lo spazio)
        # e poi rimuoviamo tutti i caratteri non numerici per estrarre la data base di 10 cifre.
        
        t_date_base_raw = line[8:25] # Contiene '161030215527.59' con spazi
        t_date_base_num = ''.join(filter(str.isdigit, t_date_base_raw))
        
        # Estrarre gli ultimi 10 caratteri: '1610302155'
        t_date_base = t_date_base_num[:10]
        
        # Verifica se è un numero valido (10 cifre)
        if len(t_date_base) != 10 or not t_date_base.isdigit():
             continue

        
        # ----------------------------------
        # --- 2.1. Elaborazione Fase P (EP) ---
        # ----------------------------------
        phase_p = line[4:6].strip()
        if phase_p == 'EP' and len(line) >= 25:
            
            # Peso P: Posizione 8 (indice 7)
            w_p_char = line[7:8].strip() 
            
            # Tempo P: Posizioni 9-25 (es. ' 1610300032 8.68')
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
            
        # ----------------------------------
        # --- 2.2. Elaborazione Fase S (ES) ---
        # ----------------------------------
        
        # S-Time Seconds: Colonne 32-36 (Indici 31-36, pulendo lo spazio)
        t_s_sec_raw = line[31:36].strip() 
        
        # Se il campo S-Time non è vuoto, estrai la fase S
        if t_s_sec_raw: 
            
            # S-Weight: Colonna 40 (Indice 39)
            w_s_char = line[39:40].strip()
            
            # Ricostruisce il tempo S completo (YYMMDDHHMMSS.SS)
            if '.' in t_s_sec_raw:
                s_parts = t_s_sec_raw.split('.')
                t_s_sec = s_parts[0].zfill(2)
                t_s_dec = s_parts[1]
            else:
                t_s_sec = t_s_sec_raw.zfill(2)
                t_s_dec = ''
            
            # RI-COSTRUZIONE CRITICA: YYMMDDHHMM + SS + .SS (t_date_base è garantita 10 cifre)
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

    print(f"   *** DEBUG: Righe totali .phs lette: 94. Fasi totali estratte: {lines_added}. ***")
    
    if df_phs.empty:
        df_phs_final = pd.DataFrame(columns=['station_name', 'phase', 'arrival_time_str', 'weight', 'ID'])
        print("   Total phases matched to final events: 0")
        print("-" * 40)
        return df_loc_final, df_phs_final


    # 3. Pulizia e Mappatura Pesi
    df_phs['weight_int'] = pd.to_numeric(df_phs['weight_char'], errors='coerce').fillna(3).astype(np.int64)
    df_phs['weight'] = df_phs['weight_int'].replace(WEIGHT_MAP) 
    df_phs = df_phs[df_phs['weight_int'] != 4].drop(columns=['weight_int', 'weight_char']).copy()
    
    # --- ESEGUI IL MERGE ---
    df_loc_final['PHS_ID_Match'] = df_loc_final['ID'] 
    
    df_phs_final = pd.merge(
        df_phs,
        df_loc_final[['ID', 'PHS_ID_Match']],
        left_on='PHS_ID',
        right_on='PHS_ID_Match',
        how='inner'
    ).drop(columns=['PHS_ID', 'PHS_ID_Match']).copy()
    
    print(f"   Total phases matched to final events: {len(df_phs_final)}")
    sample_debug_ids = [1594, 1595, 1596, 2965, 2966, 2967]
    sample_matches = df_loc_final[df_loc_final['ID'].isin(sample_debug_ids)][['T', 'ID']].copy()
    if not sample_matches.empty:
        print("   DEBUG sample mapped event IDs from quality:")
        print(sample_matches.to_string(index=False))
    print("-" * 40)
    
    
    # BLOCCO DI DEBUG MODIFICATO: Mostra solo l'evento con ID 3
    print(">>> ESEMPIO DI FASI PRONTE PER HYPODD (EVENTO ID 3):")
    df_event_3 = df_phs_final[df_phs_final['ID'] == 21].copy()
    
    if df_event_3.empty:
        print("Nessuna fase trovata per l'evento ID 3.")
    else:
        # Stampiamo tutte le colonne pertinenti per la verifica
        print(df_event_3[['station_name', 'phase', 'arrival_time_str', 'weight', 'ID']]) 
    print("-" * 40)
    
    return df_loc_final, df_phs_final

# --- 4. File Generation Function (FIX S > 60 SECONDI) ---

def create_hypodd_combined_file(df_loc_final, df_phs_final):
    """
    Generates the hypoDD combined input file, calculating travel times.
    """
    print(f"5. Starting generation of combined output file: {OUTPUT_FILE}")

    # Prepare Origin Times (T)
    origin_times = {}
    for index, row in df_loc_final.iterrows():
        t_full_str = str(row['T']).replace('_', '') 
        
        dt, ot_sec_dec, ot_epoch = parse_origin_time(t_full_str)
        
        if dt and ot_epoch:
            origin_times[row['ID']] = (dt, ot_sec_dec, ot_epoch)

    # Funzione per parsare i tempi di arrivo delle fasi (FIX: gestisce SS > 60)
    def parse_phase_time(t_str):
        t_str = str(t_str).strip()
        if len(t_str) < 13: 
            return None, None, None

        date_part = t_str[:10] # YYMMDDHHMM
        sec_part_raw = t_str[10:] # SS.SS
        
        if '.' in sec_part_raw:
            parts = sec_part_raw.split('.')
            sec_part = parts[0].zfill(2)
            sec_decimal_part = parts[1]
        else:
            sec_part = sec_part_raw.zfill(2)
            sec_decimal_part = '0'
        
        
        # --- LOGICA ROLL-OVER > 60 SECONDI APPLICATA QUI ---
        
        # Estraiamo data e ora (YYMMDDHHMM) e secondi totali (SS.SS)
        try:
            sec_float = float(sec_part) + float("0." + sec_decimal_part)
            
            # Converte la base (YYMMDDHHMM) in datetime iniziale
            dt_base = datetime.strptime(date_part, '%y%m%d%H%M')
            
            # Aggiunge i secondi totali (che potrebbero essere > 60)
            dt_full_arrival = dt_base + pd.Timedelta(seconds=sec_float)
            
            # Riformatta nel formato necessario per l'Epoch
            epoch_sec = dt_full_arrival.timestamp()
            
            # Ricalcola la stringa tempo per il debug (opzionale, ma utile)
            # time_str_for_debug = dt_full_arrival.strftime('%y%m%d%H%M%S') + '.' + sec_decimal_part[:2]

            return dt_full_arrival, sec_float, epoch_sec
            
        except ValueError:
            return None, None, None


    # Calcolo di arrivo epoch per le fasi
    if df_phs_final.empty:
        df_phs_final_processed = df_phs_final
    else:
        df_phs_final_processed = df_phs_final.copy()
        
        # Nota: Usiamo .apply per ottenere il risultato corretto in colonna 2 (epoch)
        df_phs_final_processed[['dt_arr', 'arr_sec_float', 'arrival_epoch']] = df_phs_final_processed['arrival_time_str'].apply(
            lambda x: pd.Series(parse_phase_time(x))
        )
        # Se una fase fallisce il parsing (es. tempo non numerico), viene scartata qui
        df_phs_final_processed = df_phs_final_processed.dropna(subset=['arrival_epoch']).copy()


    try:
        with open(OUTPUT_FILE, 'w') as f:
            df_loc_sorted = df_loc_final.sort_values(by='ID')
            
            for index, event in df_loc_sorted.iterrows():
                event_id = event['ID']
                ot_data = origin_times.get(event_id)
                if ot_data is None: continue 

                ot_dt, ot_sec_dec, ot_epoch = ot_data
                
                # --- A. Write Event Line (#) ---
                ot_sec_float = ot_dt.second + ot_sec_dec
                
                # FORMATTAZIONE: Spazio dopo '#'
                event_line = (
                    f"# {ot_dt.year:<4} {ot_dt.month:>2} {ot_dt.day:>2} {ot_dt.hour:>2} "
                    f"{ot_dt.minute:>2} {ot_sec_float:>6.2f} "
                    f"{event['LAT']:>10.5f} {event['LON']:>10.5f} {event['DEP']:>8.4f} "
                    f"0.00000 0.00000 0.00000 0.00000 "
                    f"{event_id:>4}"
                )
                f.write(event_line + "\n")
                
                # --- B. Write Phase Lines (Travel Times) ---
                if not df_phs_final_processed.empty:
                    event_phases = df_phs_final_processed[df_phs_final_processed['ID'] == event_id].copy() 
                    
                    if not event_phases.empty:
                        # Calcolo Travel Time: Differenza tra le due epoche
                        event_phases['travel_time'] = event_phases['arrival_epoch'] - ot_epoch
                        
                        for i, phase in event_phases.iterrows():
                            # Stazione 5 caratteri
                            phase_line = (
                                f"{phase['station_name']:<5} {phase['travel_time']:>6.3f} "
                                f"{phase['weight']:>6.3f} {phase['phase']}"
                            )
                            f.write(phase_line + "\n")
                    
        print(f"✅ File '{OUTPUT_FILE}' created successfully.")
        
    except IOError as e:
        print(f"❌ Error writing file: {e}")

# --- 5. Station File Generation Function ---

def create_station_file():
    """
    Reads station data from the CSV and generates the station.dat file
    formatted as: STATION_NAME LAT LON Z (quota in metri senza decimali).
    """
    print(f"6. Starting generation of station file: {STATION_FILE}")
    
    try:
        # Legge solo le colonne necessarie
        df_stations = pd.read_csv(
            STATIONS_FILE, 
            usecols=['station', 'latitude', 'longitude', 'elevation']
        )
        
        # Rinominare per chiarezza
        df_stations.columns = ['NAME', 'LAT', 'LON', 'Z']
        
        # Elimina duplicati e dati nulli
        df_stations = df_stations.dropna().drop_duplicates(subset=['NAME'])
        
    except FileNotFoundError:
        print(f"❌ ERROR: Stations file not found at {STATIONS_FILE}. Skipping station.dat generation.")
        return
    except KeyError as e:
        print(f"❌ ERROR: Column {e} not found in stations.csv. Check column names.")
        return
    
    try:
        with open(STATION_FILE, 'w') as f:
            for index, row in df_stations.iterrows():
                # Formato richiesto (NAME LAT LON Z):
                # Z è l'elevation in metri. Modifica: uso .0f per rimuovere i decimali.
                
                station_line = (
                    f"{row['NAME']:<6} "
                    f"{row['LAT']:>10.6f} "
                    f"{row['LON']:>10.6f} "
                    f"{row['Z']:>10.0f}" # MODIFICA: Quota in metri senza decimali (0f)
                )
                f.write(station_line + "\n")
                
        print(f"✅ File '{STATION_FILE}' created successfully with {len(df_stations)} stations.")
        
    except IOError as e:
        print(f"❌ Error writing station file: {e}")


# --- 6. Main Execution Block ---

if __name__ == '__main__':
    
    # 1. Read and filter data
    df_loc_final, df_phs_final = read_and_filter_data()
    
    # 2. Check if there are events remaining
    if not df_loc_final.empty:
        # 3. Generate the final combined output file
        create_hypodd_combined_file(df_loc_final, df_phs_final)
        
    else:
        print("🛑 No events passed the quality filters or could be matched. Output file not generated.")
        
    # 4. Generate the station file (va fatto a prescindere dal numero di eventi)
    create_station_file() # <<< NUOVA CHIAMATA
