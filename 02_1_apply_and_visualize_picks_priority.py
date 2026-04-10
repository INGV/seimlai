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

def get_peak_amplitude(pick_time, stream_raw, inv_path, log_file, window_sec=2.0):
    """
    Calcola l'ampiezza e logga eventuali errori sul singolo pick.
    """
    try:
        t = UTCDateTime(pick_time)
        st_wide = stream_raw.slice(t - 30.0, t + 30.0).copy()

        if len(st_wide) == 0:
            return np.nan

        st_wide.detrend("demean")
        st_wide.taper(max_percentage=0.05)
        
        if os.path.exists(inv_path):
            inv = read_inventory(inv_path)
            pre_filt = [0.1, 0.5, 30.0, 40.0]
            st_wide.remove_response(inventory=inv, output="VEL", pre_filt=pre_filt)

        st_strict = st_wide.slice(t - 1.0, t + window_sec)
        
        max_amp = 0.0
        for tr in st_strict:
            tr_max = np.max(np.abs(tr.data))
            if tr_max > max_amp:
                max_amp = tr_max

        return float(max_amp)
    except Exception as e:
        # Se c'è un errore imprevisto, lo stampiamo e lo scriviamo nel log
        err_msg = f"    Error calculating amplitude for pick at {pick_time}: {e}"
        print(err_msg)
        log_file.write(err_msg + "\n")
        return np.nan

# --- MAIN LOOP ---
for day in range(start_day, end_day + 1):
    log_file.write(f"Processing day: {day}\n")
    print(f"Processing day: {day}")
    daily_csv = os.path.join(output_picks_dir, f"picks_{year}_{day:03d}.csv")
    if os.path.exists(daily_csv):
        os.remove(daily_csv)

    if not os.path.exists(waveform_base):
        print(f"Waveform directory not found: {waveform_base}")
        continue

    for net in sorted(os.listdir(waveform_base)):
        net_path = os.path.join(waveform_base, net)
        if not os.path.isdir(net_path):
            continue

        print(f"Network: {net}")
        log_file.write(f"Network: {net}\n")

        for stat in sorted(os.listdir(net_path)):
            stat_path = os.path.join(net_path, stat)
            if not os.path.isdir(stat_path):
                continue

            print(f"Processing station: {stat}")
            log_file.write(f"Station: {stat}\n")
            stream = Stream()

            # =================================================================
            # === MODIFICA: SELEZIONE GERARCHICA CANALI (HH > EH > BH) ===
            # =================================================================
            # 1. Scansioniamo tutte le cartelle .D disponibili per questa stazione
            all_subdirs = [d for d in os.listdir(stat_path) if d.endswith(".D")]
            
            # 2. Raggruppiamo per componente (Z, N, E, 1, 2)
            #    candidates = { 'Z': [(priorità, nome_cartella), ...], '1': ... }
            candidates = {}
            
            for subdir in all_subdirs:
                try:
                    # Estraiamo il codice canale (es. "HHZ" da "HHZ.D" o "IV.STA..HHZ.D")
                    chan_code = subdir.split(".")[-2] 
                    if len(chan_code) < 3: continue
                    
                    band_inst = chan_code[:2] # es. "HH", "BH", "EH"
                    component = chan_code[2]  # es. "Z", "N", "E", "1", "2"
                    
                    # Assegniamo priorità: 0=HH (migliore), 1=EH, 2=BH, 99=Altro
                    if band_inst == "HH": priority = 0
                    elif band_inst == "EH": priority = 1
                    elif band_inst == "BH": priority = 2
                    else: priority = 99
                    
                    if component not in candidates:
                        candidates[component] = []
                    candidates[component].append((priority, subdir))
                    
                except Exception as e:
                    print(f"Skipping subdir parsing {subdir}: {e}")

            # 3. Selezioniamo SOLO la cartella migliore per ogni componente
            selected_subdirs = []
            for comp, subdir_list in candidates.items():
                # Ordina per priorità (numero più basso vince)
                subdir_list.sort(key=lambda x: x[0])
                best_subdir = subdir_list[0][1] 
                selected_subdirs.append(best_subdir)

            # 4. Leggiamo SOLO le cartelle selezionate
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
                            print(f"Error reading {fname}: {e}")
                            log_file.write(f"Error reading {fname}: {e}\n")
            
            # =================================================================
            # === FINE SELEZIONE GERARCHICA ===
            # =================================================================

            log_file.write(f"    Stream traces loaded: {len(stream)}\n")

            if len(stream) < 3:
                print("Skipped: Not enough components (needs 3)")
                log_file.write("Skipped: Not enough components\n")
                continue

            try:
                #log_file.write("    Running model.annotate()...\n")
                #annotations = model.annotate(stream)
                
                log_file.write("    Running model.classify()...\n")
                classified = model.classify(stream, batch_size=BATCH_SIZE, P_threshold=P_THRESHOLD, S_threshold=S_THRESHOLD)
                outputs = classified.picks
                log_file.write("    Classification complete.\n")
                
                # --- PLOTTING SECTION (SOLO Z + PROBABILITÀ) ---
                """ z_trace = next((trace for trace in stream if trace.stats.channel.endswith('Z')), None)
                
                if z_trace is not None and z_trace.stats.endtime - z_trace.stats.starttime > 0:
                    
                    start_time = z_trace.stats.starttime
                    end_time = z_trace.stats.endtime
                    duration = end_time - start_time
                    
                    num_segments = math.ceil(duration / WLENGTH_SECONDS)
                    N_rows = num_segments * 2
                    
                    fig_height = num_segments * 3.5 
                    fig = plt.figure(figsize=(15, fig_height))
                    
                    height_ratios = [3, 1] * num_segments
                    gs = fig.add_gridspec(N_rows, 1, hspace=0.01, height_ratios=height_ratios) 
                    
                    print(f"    Generating plot with {num_segments} segments...")

                    # Liste per la legenda unica
                    all_handles = []
                    all_labels = []
                    
                    for i in range(num_segments):
                        window_start = start_time + i * WLENGTH_SECONDS
                        window_end = min(start_time + (i + 1) * WLENGTH_SECONDS, end_time)
                        
                        if window_end <= window_start:
                            break
                        
                        sliced_trace = z_trace.slice(window_start, window_end)
                        sliced_annotations = annotations.slice(window_start, window_end)
                        
                        if len(sliced_trace.data) == 0:
                            continue
                        
                        # --- 1. Plot Traccia Sismica (Z) ---
                        ax_trace = fig.add_subplot(gs[2*i, 0]) 
                        
                        if i < num_segments - 1:
                            ax_trace.tick_params(axis='x', labelbottom=False)
                        
                        max_abs_data = max(abs(sliced_trace.data)) if len(sliced_trace.data) > 0 else 1
                        normalized_data = sliced_trace.data / max_abs_data
                        
                        label_norm = f"Norm. {sliced_trace.stats.channel}" if i == 0 else ""
                        ax_trace.plot(sliced_trace.times(), normalized_data, color='k', label=label_norm) 
                    
                        ax_trace.set_ylabel(f"Norm. {sliced_trace.stats.channel}\n({window_start.strftime('%H:%M')})", fontsize=8)
                        ax_trace.tick_params(axis='x', labelbottom=False)
                        if i == 0:
                            ax_trace.set_title(f"Picks for {net}.{stat} - Day {day:03d}")
                        
                        # Raccogli legenda
                        if i == 0:
                            h, l = ax_trace.get_legend_handles_labels()
                            all_handles.extend(h)
                            all_labels.extend(l)
                        
                        ax_trace.tick_params(axis='y', length=0)
                        ax_trace.set_yticks([]) 
                        ax_trace.set_xlim(0, WLENGTH_SECONDS)

                        # --- 2. Plot Probabilità ---
                        ax_preds = fig.add_subplot(gs[2*i + 1, 0])
                        ax_preds.set_xlim(ax_trace.get_xlim())                        

                        colors = {"P": "C0", "S": "C1", "N": "C2"}
                        
                        for trace in sliced_annotations:
                            phase = trace.stats.channel.split('_')[-1] 
                            if phase in colors:
                                label = f"Prob. {phase}" if i == 0 else ''
                                ax_preds.plot(trace.times(), trace.data, color=colors[phase], label=label)

                        ax_preds.set_ylabel("Prob.", fontsize=8)
                        ax_preds.set_ylim(0, 1)

                        if i == 0:
                            h, l = ax_preds.get_legend_handles_labels()
                            all_handles.extend(h)
                            all_labels.extend(l)
                            
                        if i == num_segments - 1:
                            ax_preds.set_xlabel("Time [s]") 
                        else:
                            ax_preds.tick_params(axis='x', labelbottom=False)
                        
                        ax_preds.tick_params(axis='y', length=0)
                        ax_preds.set_yticks([0, 0.5, 1]) 
                    
                    # Legenda Unica
                    unique_legend = dict(zip(all_labels, all_handles))
                    fig.legend(unique_legend.values(), unique_legend.keys(), loc='upper center', ncol=6, bbox_to_anchor=(0.5, 0.99))
                    
                    figure_filename = os.path.join(plot_dir, f"{net}_{stat}_{year}_{day:03d}_FULL_Z_annotations.pdf")
                    plt.savefig(figure_filename, bbox_inches='tight', format='pdf', dpi=300) 
                    plt.close(fig) 
                    log_file.write(f"    Plot saved: {figure_filename}\n") """
                inv_path = os.path.join(inventory_dir, f"{net}.{stat}.xml")
                # --- CONTROLLO ESISTENZA XML ---
                if os.path.exists(inv_path):
                    log_file.write(f"    XML inventory found. Amplitudes will be calculated in VEL.\n")
                else:
                    print(f"Warning: XML non trovato per {net}_{stat}. L'ampiezza rimarrà in Counts.")
                    log_file.write(f"    Warning: XML not found for {net}_{stat}. Amplitude in Counts.\n")
                # --- SALVATAGGIO CSV ---
                pick_df = []
                for p in outputs:
                    amp_val = get_peak_amplitude(p.peak_time.datetime, stream, inv_path, log_file)
                    pick_df.append({
                        "station": stat,
                        "id": p.trace_id,
                        "timestamp": p.peak_time.datetime,
                        "prob": p.peak_value,
                        "amp": amp_val,
                        "type": p.phase.lower()
                    })
                pick_df = pd.DataFrame(pick_df)
                
                # Append to CSV
                pick_df.to_csv(daily_csv, mode='a', index=False, header=not os.path.exists(daily_csv))
                log_file.write(f"    Picks saved: {len(pick_df)}\n")

            except Exception as e:
                print(f"Error on {stat}: {e}")
                log_file.write(f"Error on {stat}: {e}\n")

            #del stream, annotations, classified, outputs
            del stream, classified, outputs
            gc.collect() 

    # Sort CSV at the end of the day
    try:
        if os.path.exists(daily_csv):
            df = pd.read_csv(daily_csv)
            if not df.empty:
                df = df.sort_values("timestamp")
                df.to_csv(daily_csv, index=False)
                log_file.write(f"Daily CSV sorted: {daily_csv}\n")
    except Exception as e:
        log_file.write(f"Error sorting daily CSV: {e}\n")

# End timing
overall_end_time = time.time()
total_duration = overall_end_time - overall_start_time
print(f"Total picking time: {total_duration:.2f} seconds")
log_file.write("="*60 + "\n")
log_file.write(f"Total picking time: {total_duration:.2f} seconds\n")
log_file.close()
