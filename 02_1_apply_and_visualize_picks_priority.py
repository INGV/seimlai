#!/usr/bin/env python
# coding: utf-8

# Picks P- and S- wave arrival times for each stations. 
# Uses PhaseNet with Seisbench.
# Optimized to handle channel hierarchy (HH > EH > BH) and non-standard components (1, 2).

# import libraries
import os
import gc
import time
import re
import math
from obspy import read, Stream, Trace, UTCDateTime, read_inventory
from seisbench.models import PhaseNet
import pandas as pd
import numpy as np
import torch
import matplotlib.pyplot as plt 
import matplotlib.dates as mdates 
import matplotlib.gridspec as gridspec
import numpy as np
import os
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed
from config import *

# --- CONFIGURAZIONE DEVICE & MODELLO ---
# device, device_name e model sono importati da config.py
print(f"Using {device_name} for processing.")
print(f"Model loaded and ready on {device}")


os.makedirs(output_picks_dir, exist_ok=True)
#os.makedirs(plot_dir, exist_ok=True) 

# --- LOGGING ---
log_file = open(log_file_path, "w")
log_file.write(f"PhaseNet Picking Log - Year: {year}, Days: {start_day} to {end_day}\n")
log_file.write(f"Plotting segment length (WLENGTH_SECONDS): {WLENGTH_SECONDS} seconds\n")
log_file.write("Hierarchy applied: HH > EH > BH\n")
log_file.write("="*60 + "\n")

# Start timing
overall_start_time = time.time()

def get_peak_amplitude(pick_time, stream_vel, logs, window_sec=2.0):
    """
    Cerca l'ampiezza massima su una traccia già convertita in velocità (VEL).
    Salva eventuali errori nella lista 'logs' invece che direttamente sul file.
    """
    try:
        t = UTCDateTime(pick_time)
        st_strict = stream_vel.slice(t - 1.0, t + window_sec)
        
        if len(st_strict) == 0:
            return np.nan
            
        max_amp = 0.0
        for tr in st_strict:
            tr_max = np.max(np.abs(tr.data))
            if tr_max > max_amp:
                max_amp = tr_max

        return float(max_amp)
    except Exception as e:
        err_msg = f"    Error calculating amplitude for pick at {pick_time}: {e}"
        print(err_msg)
        logs.append(err_msg)
        return np.nan


# --- FUNZIONE WORKER (Lavora in parallelo) ---
def process_station_worker(args):
    net, stat, day, stat_path, inv_path, year = args
    logs = []  # Lista temporanea per i messaggi di questa specifica stazione
    pick_df_list = []
    
    logs.append(f"[{net}.{stat}], Giorno {day}, Inizio elaborazione...")
    stream = Stream()

    # === SELEZIONE GERARCHICA CANALI ===
    all_subdirs = [d for d in os.listdir(stat_path) if d.endswith(".D")]
    candidates = {}
    
    for subdir in all_subdirs:
        try:
            chan_code = subdir.split(".")[-2] 
            if len(chan_code) < 3: continue
            band_inst, component = chan_code[:2], chan_code[2]
            
            if band_inst == "HH": priority = 0
            elif band_inst == "EH": priority = 1
            elif band_inst == "BH": priority = 2
            else: priority = 99
            
            if component not in candidates: candidates[component] = []
            candidates[component].append((priority, subdir))
        except Exception:
            pass

    selected_subdirs = []
    for comp, subdir_list in candidates.items():
        subdir_list.sort(key=lambda x: x[0])
        selected_subdirs.append(subdir_list[0][1])

    for subdir in selected_subdirs:
        full_path = os.path.join(stat_path, subdir)
        if os.path.isdir(full_path):
            for fname in os.listdir(full_path):
                try:
                    match = re.match(r".*\.(\d{4})\.(\d{3})$", fname)
                    if match:
                        file_year, file_day = int(match.group(1)), int(match.group(2))
                        if file_year == year and file_day == day:
                            stream += read(os.path.join(full_path, fname))
                except Exception as e:
                    logs.append(f"[{net}.{stat}] Errore lettura {fname}: {e}")
    
    if len(stream) < 3:
        logs.append(f"[{net}.{stat}] Skipped: Non ha 3 componenti.")
        return pd.DataFrame(), logs

    try:
        # Rimozione Risposta Strumentale
        stream_vel = stream.copy()
        stream_vel.detrend("demean")
    
        if os.path.exists(inv_path):
            inv = read_inventory(inv_path)
            pre_filt = [0.1, 0.5, 30.0, 40.0]
            stream_vel.remove_response(inventory=inv, output="VEL", pre_filt=pre_filt)
        else:
            logs.append(f"[{net}.{stat}] Warning: XML non trovato. Ampiezza in Counts.")

        # Rete Neurale (model, BATCH_SIZE, P_THRESHOLD, S_THRESHOLD vengono presi da config.py)
        classified = model.classify(stream, batch_size=BATCH_SIZE, P_threshold=P_THRESHOLD, S_threshold=S_THRESHOLD)
        outputs = classified.picks
        
        # Calcolo ampiezze e salvataggio locale
        for p in outputs:
            amp_val = get_peak_amplitude(p.peak_time.datetime, stream_vel, logs)
            pick_df_list.append({
                "station": stat,
                "id": p.trace_id,
                "timestamp": p.peak_time.datetime,
                "prob": p.peak_value,
                "amp": amp_val,
                "type": p.phase.lower()
            })
            
        logs.append(f"[{net}.{stat}] Completato. Trovati {len(pick_df_list)} picks.")

    except Exception as e:
        logs.append(f"[{net}.{stat}] Errore su {stat}: {e}")

    # Pulizia RAM
    del stream, stream_vel
    if 'classified' in locals(): del classified, outputs
    gc.collect()

    return pd.DataFrame(pick_df_list), logs

# =====================================================================
# --- MAIN SCRIPT ---
# =====================================================================
if __name__ == '__main__':
    # Configurazione vitale per PyTorch e multiprocessing su CUDA
    if device.type == "cuda":
        try:
            mp.set_start_method('spawn', force=True)
        except RuntimeError:
            pass

    if device.type == "mps" or device.type == "cpu":
        NUM_WORKERS = 2  # Freno a mano sul Mac: fa 1 stazione alla volta
    else:
        NUM_WORKERS = mp.cpu_count()  #Cluster
    print(f"Avvio elaborazione parallela con {NUM_WORKERS} WORKERS!")

    for day in range(start_day, end_day + 1):
        log_file.write(f"\n--- Processing day: {day} ---\n")
        print(f"\nProcessing day: {day}")
        
        daily_csv = os.path.join(output_picks_dir, f"picks_{year}_{day:03d}.csv")
        if os.path.exists(daily_csv):
            os.remove(daily_csv)

        if not os.path.exists(waveform_base):
            continue

        # 1. Creiamo la lista delle stazioni da processare
        tasks = []
        for net in sorted(os.listdir(waveform_base)):
            net_path = os.path.join(waveform_base, net)
            if not os.path.isdir(net_path): continue

            for stat in sorted(os.listdir(net_path)):
                stat_path = os.path.join(net_path, stat)
                if not os.path.isdir(stat_path): continue
                
                inv_path = os.path.join(inventory_dir, f"{net}.{stat}.xml")
                tasks.append((net, stat, day, stat_path, inv_path, year))

        # 2. Eseguiamo il calcolo in parallelo su tutti i core
        all_daily_picks = []
        with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = {executor.submit(process_station_worker, task): task for task in tasks}
            
            for future in as_completed(futures):
                df_station, worker_logs = future.result()
                
                # Scriviamo i log in modo sicuro e in ordine
                for msg in worker_logs:
                    log_file.write(msg + "\n")
                    print(msg) 
                
                if not df_station.empty:
                    all_daily_picks.append(df_station)

        # 3. Alla fine della giornata, salviamo tutto nel CSV
        if all_daily_picks:
            try:
                final_daily_df = pd.concat(all_daily_picks, ignore_index=True)
                final_daily_df = final_daily_df.sort_values("timestamp")
                final_daily_df.to_csv(daily_csv, index=False)
                log_file.write(f"Daily CSV sorted and saved: {daily_csv}\n")
            except Exception as e:
                log_file.write(f"Error sorting/saving daily CSV: {e}\n")

    overall_end_time = time.time()
    total_duration = overall_end_time - overall_start_time
    print(f"\nTotal picking time: {total_duration:.2f} seconds")
    log_file.write("="*60 + "\n")
    log_file.write(f"Total picking time: {total_duration:.2f} seconds\n")
    log_file.close()
