#!/usr/bin/env python
# coding: utf-8

# =====================================================================
# --- LIBRERIE ESTERNE ---
# =====================================================================
import os
import gc
import time
import re
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd
import torch
from obspy import read, Stream, UTCDateTime, read_inventory


# =====================================================================
# --- 1. FUNZIONI DI SUPPORTO ---
# =====================================================================
def get_peak_amplitude(pick_time, stream_vel, logs, window_sec=2.0):
    """
    Cerca l'ampiezza massima su una traccia già convertita in velocità (VEL).
    Salva gli errori in 'logs' per non creare conflitti tra i core in scrittura.
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
        logs.append(err_msg)
        return np.nan


# =====================================================================
# --- 2. FUNZIONE WORKER (Eseguita dai singoli core) ---
# =====================================================================
def process_station_worker(args):
    # IMPORT LOCALE: Il worker carica dal config solo i parametri del modello.
    # Questo permette alla GPU di attivarsi in totale sicurezza per ogni processo.
    from config import BATCH_SIZE, P_THRESHOLD, S_THRESHOLD, model
    
    # FRENO CPU: Evita l'ingorgo matematico tra i 16 worker attivi
    torch.set_num_threads(1)
    
    net, stat, day, stat_path, inv_path, year = args
    logs = []
    pick_df_list = []
    
    # STAMPA LIVE
    print(f"🔄 [Worker] -> Sto processando la stazione: {net}.{stat} (Giorno {day})", flush=True)
    logs.append(f"[{net}.{stat}] Inizio elaborazione...")
    
    stream = Stream()

    # === SELEZIONE GERARCHICA CANALI (HH > EH > BH) ===
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

    # === LETTURA FILE SISMICI ===
    # === LETTURA FILE SISMICI ===
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

    # Se non ha letto nulla, restituisce subito liste vuote
    if len(stream) == 0:
        return pd.DataFrame(), logs

    # =========================================================
    #  1. SCUDO MORBIDO SUI GAP (Salva dati buoni e RAM)
    # =========================================================
    try:
        stream.sort()
        # Misuriamo la lunghezza totale dei dati
        t_start = stream[0].stats.starttime
        t_end = stream[-1].stats.endtime
        durata_ore = (t_end - t_start) / 3600.0

        # Mettiamo un limite di "sopravvivenza" largo (48 ore) per gestire i file enormi a cavallo di mezzanotte
        if durata_ore <= 48.0:
            stream.merge(method=1, fill_value=0)
        else:
            logs.append(f"[{net}.{stat}] SKIP: Dati corrotti (Durata: {durata_ore:.1f}h). Rischio OOM!")
            return pd.DataFrame(), logs
            
    except Exception as e:
        logs.append(f"[{net}.{stat}] Errore durante il controllo/merge: {e}")
        return pd.DataFrame(), logs
    # =========================================================

    # Se dopo il merge non abbiamo le 3 componenti sane, saltiamo la stazione
    if len(stream) < 3:
        logs.append(f"[{net}.{stat}] Skipped: Non ha 3 componenti.")
        return pd.DataFrame(), logs
    try:
        # === RIMOZIONE RISPOSTA STRUMENTALE ===
        # === RIMOZIONE RISPOSTA STRUMENTALE ===
        stream_vel = stream.copy()
        stream_vel.detrend("demean")

        # =========================================================
        # ✨ 3. RICERCA ESATTA DELL'XML CON STAMPA LIVE
        # =========================================================
        xml_reale = None
        cartella_xml = os.path.dirname(inv_path)
        nome_esatto_xml = f"{net}.{stat}.xml" # Es: 3A.MZ09.xml

        if os.path.exists(cartella_xml):
            for f in os.listdir(cartella_xml):
                # Il nome del file deve essere ESATTAMENTE quello che cerchiamo
                if f == nome_esatto_xml:
                    xml_reale = os.path.join(cartella_xml, f)
                    break

        if xml_reale is not None:
            from obspy import read_inventory
            inv = read_inventory(xml_reale)

            # --- SOLUZIONE GENERALIZZATA ---
            original_channels = []
            for tr in stream_vel:
                original_channels.append(tr.stats.channel)
                comp = tr.stats.channel[-1]

                xml_channels = [c.code for n in inv for s in n for c in s]

                if tr.stats.channel not in xml_channels:
                    fallback = [c for c in xml_channels if c.endswith(comp)]
                    if fallback:
                        tr.stats.channel = fallback[0]

            pre_filt = [0.1, 0.5, 30.0, 40.0]
            try:
                stream_vel.remove_response(inventory=inv, output="VEL", pre_filt=pre_filt, water_level=60)

                # STAMPA LIVE: SUCCESSO!
                nome_file_trovato = os.path.basename(xml_reale)
                print(f"[XML] {net}.{stat} -> Trovato ({nome_file_trovato}) | Convertito in VEL (m/s)", flush=True)

            except Exception as e:
                logs.append(f"[{net}.{stat}] Errore remove_response: {e}. Provo senza risposta.")
                # STAMPA LIVE: ERRORE MATEMATICO (Es. XML corrotto all'interno)
                print(f"[XML] {net}.{stat} -> Trovato ({nome_file_trovato}), ma Errore Matematico | Mantenuto in Counts", flush=True)

            for i, tr in enumerate(stream_vel):
                tr.stats.channel = original_channels[i]

        else:
            logs.append(f"[{net}.{stat}] Warning: XML {nome_esatto_xml} non trovato in {cartella_xml}. Ampiezza in Counts.")
            # STAMPA LIVE: FILE MANCANTE
            print(f" [XML] {net}.{stat} -> {nome_esatto_xml} NON TROVATO | Mantenuto in Counts", flush=True)

        # === INFERENZA RETE NEURALE ===
        # === INFERENZA RETE NEURALE ===
        classified = model.classify(stream, batch_size=BATCH_SIZE, P_threshold=P_THRESHOLD, S_threshold=S_THRESHOLD)
        outputs = classified.picks
        
        # === ESTRAZIONE AMPIEZZE ===
        # === ESTRAZIONE AMPIEZZE ===
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
        logs.append(f"[{net}.{stat}] Errore fatale su {stat}: {e}")

    # === PULIZIA MEMORIA RAM ===
    del stream, stream_vel
    if 'classified' in locals(): del classified, outputs
    import gc
    gc.collect()

    return pd.DataFrame(pick_df_list), logs


# =====================================================================
# --- 3. MAIN SCRIPT (Il "Direttore d'orchestra") ---
# =====================================================================
if __name__ == '__main__':
    # 1. OBBLIGATORIO: Prepariamo il multiprocessing PRIMA di attivare la GPU
    try:
        mp.set_start_method('spawn', force=True)
    except RuntimeError:
        pass

    # 2. SOLO ORA importiamo le directory e i parametri generali dal config
    from config import *

    os.makedirs(output_picks_dir, exist_ok=True)

    log_file = open(log_file_path, "w")
    log_file.write(f"PhaseNet Parallel Picking Log - Year: {year}, Days: {start_day} to {end_day}\n")
    log_file.write("="*60 + "\n")

    overall_start_time = time.time()

    # 3. LETTURA RISORSE DI CALCOLO
    if device.type == "mps" or device.type == "cpu":
        NUM_WORKERS = 2  # Freno a mano per test su Mac
    else:
        # Sul Cluster, legge dinamicamente i core che hai chiesto con #SBATCH
        slurm_cpus = int(os.environ.get('SLURM_CPUS_PER_TASK', 4))
        NUM_WORKERS = slurm_cpus

    print(f"Avvio elaborazione parallela con {NUM_WORKERS} WORKERS!", flush=True)
    log_file.write(f"Workers: {NUM_WORKERS}\n")

    # 4. CICLO SUI GIORNI
    for day in range(start_day, end_day + 1):
        log_file.write(f"\n--- Processing day: {day} ---\n")
        print(f"\nProcessing day: {day}", flush=True)
        
        daily_csv = os.path.join(output_picks_dir, f"picks_{year}_{day:03d}.csv")
        if os.path.exists(daily_csv):
            os.remove(daily_csv)

        if not os.path.exists(waveform_base):
            continue

        # Preparazione dei pacchetti di lavoro (tasks) per le stazioni
        tasks = []
        for net in sorted(os.listdir(waveform_base)):
            net_path = os.path.join(waveform_base, net)
            if not os.path.isdir(net_path): continue

            for stat in sorted(os.listdir(net_path)):
                stat_path = os.path.join(net_path, stat)
                if not os.path.isdir(stat_path): continue
                
                inv_path = os.path.join(inventory_dir, f"{net}.{stat}.xml")
                tasks.append((net, stat, day, stat_path, inv_path, year))

        # Esecuzione in parallelo
        all_daily_picks = []
        with ProcessPoolExecutor(max_workers=NUM_WORKERS) as executor:
            futures = {executor.submit(process_station_worker, task): task for task in tasks}
            
            # Man mano che i worker finiscono, si raccolgono i risultati
            for future in as_completed(futures):
                df_station, worker_logs = future.result()
                
                # Salvataggio nel file log di tutto il lavoro della stazione
                for msg in worker_logs:
                    log_file.write(msg + "\n")
                
                if not df_station.empty:
                    all_daily_picks.append(df_station)

        # Salvataggio unico a fine giornata nel CSV
        if all_daily_picks:
            try:
                final_daily_df = pd.concat(all_daily_picks, ignore_index=True)
                final_daily_df = final_daily_df.sort_values("timestamp")
                final_daily_df.to_csv(daily_csv, index=False)
                log_file.write(f"Daily CSV sorted and saved: {daily_csv} with {len(final_daily_df)} picks.\n")
                print(f"Giorno {day} completato: {len(final_daily_df)} picks trovati.", flush=True)
            except Exception as e:
                log_file.write(f"Error sorting/saving daily CSV: {e}\n")

    # 5. CHIUSURA
    overall_end_time = time.time()
    total_duration = overall_end_time - overall_start_time
    print(f"\nTotal picking time: {total_duration:.2f} seconds", flush=True)
    log_file.write("="*60 + "\n")
    log_file.write(f"Total picking time: {total_duration:.2f} seconds\n")
    log_file.close()


def sort_seismic_picking(df, output_file):
    # Rename columns
    df = df.rename(columns={
        "station": "Station",
        "timestamp": "Datetime",
        "prob": "Probability",
        "type": "Wave_Type",
        "amp": "Amp"
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


def run_sort_picks():
    from config import output_picks_dir, start_day, end_day, year

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


def generate_combined_plots(df_plot, output_dir):
    """Generates a single PDF file containing 5 combined subplots from the aggregated data."""
    import matplotlib.pyplot as plt

    SINGLE_PDF_FILE = "combined_analysis_report.pdf"
    
    thresholds = df_plot['threshold'].astype(str)
    x = np.arange(len(thresholds))
    width = 0.6 

    fig = plt.figure(figsize=(16, 18))
    gs = fig.add_gridspec(3, 2, hspace=0.6, wspace=0.3) 
    
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, 0])
    ax4 = fig.add_subplot(gs[1, 1])
    ax5 = fig.add_subplot(gs[2, :])

    rects1 = ax1.bar(x, df_plot['num_p'], width, color='skyblue')
    ax1.set_ylabel('P-wave Count')
    ax1.set_title('1. P-wave Pick Count vs. Threshold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(thresholds)
    for rect in rects1:
        height = rect.get_height()
        ax1.text(rect.get_x() + rect.get_width()/2., height, f'{height:.0f}', ha='center', va='bottom', fontsize=8)

    rects2 = ax2.bar(x, df_plot['num_s'], width, color='salmon')
    ax2.set_ylabel('S-wave Count')
    ax2.set_title('2. S-wave Pick Count vs. Threshold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(thresholds)
    for rect in rects2:
        height = rect.get_height()
        ax2.text(rect.get_x() + rect.get_width()/2., height, f'{height:.0f}', ha='center', va='bottom', fontsize=8)

    rects3 = ax3.bar(x, df_plot['mean_p'], width, color='lightgreen')
    ax3.set_ylabel('Mean Probability')
    ax3.set_title('3. Mean P-wave Probability vs. Threshold (Mean +/- Std Dev)')
    ax3.set_xticks(x)
    ax3.set_xticklabels(thresholds)
    for rect, m_p, sd_p in zip(rects3, df_plot['mean_p'], df_plot['std_p']):
        text_label = f'{m_p:.4f} +/- {sd_p:.4f}'
        ax3.text(rect.get_x() + rect.get_width()/2., rect.get_height(), text_label, ha='center', va='bottom', fontsize=8)

    rects4 = ax4.bar(x, df_plot['mean_s'], width, color='gold')
    ax4.set_ylabel('Mean Probability')
    ax4.set_title('4. Mean S-wave Probability vs. Threshold (Mean +/- Std Dev)')
    ax4.set_xticks(x)
    ax4.set_xticklabels(thresholds)
    for rect, m_s, sd_s in zip(rects4, df_plot['mean_s'], df_plot['std_s']):
        text_label = f'{m_s:.4f} +/- {sd_s:.4f}'
        ax4.text(rect.get_x() + rect.get_width()/2., rect.get_height(), text_label, ha='center', va='bottom', fontsize=8)

    ax5.plot(thresholds, df_plot['std_p'], marker='o', linestyle='-', color='blue', label='P-wave Std Dev')
    ax5.plot(thresholds, df_plot['std_s'], marker='s', linestyle='--', color='red', label='S-wave Std Dev')
    ax5.set_ylabel('Standard Deviation of Probability')
    ax5.set_xlabel('Threshold')
    ax5.set_title('5. Probability Standard Deviation vs. Threshold (Combined Line Chart)')
    ax5.legend()
    ax5.grid(True, linestyle=':', alpha=0.6)

    for ax in [ax1, ax2, ax3, ax4, ax5]:
        ax.set_xlabel('Threshold')
        ax.tick_params(axis='x', rotation=45)

    output_path = os.path.join(output_dir, SINGLE_PDF_FILE)
    fig.tight_layout() 
    fig.savefig(output_path, format='pdf', dpi=300)
    plt.close(fig)


def analyze_data_by_threshold():
    from config import output_base, start_day, end_day, year

    BASE_DIRECTORY = output_base
    FILE_NAME = f"{start_day}_{end_day}_{year}_picks_sort.csv"
    LOG_FILE = "analysis_log.txt"
    SINGLE_PDF_FILE = "combined_analysis_report.pdf"
    
    if not os.path.exists(BASE_DIRECTORY):
        print(f"ERROR: The defined BASE_DIRECTORY '{BASE_DIRECTORY}' does not exist.")
        return

    log_path = os.path.join(BASE_DIRECTORY, LOG_FILE)
    plot_data = []
    found_any_data = False

    for root, dirs, files in os.walk(BASE_DIRECTORY):
        if os.path.basename(root).startswith('output_picks'):
            dir_name = os.path.basename(root)
            match = re.search(r'(\d+\.?\d+)', dir_name) 
            threshold_value = match.group(1) if match else dir_name
            
            if FILE_NAME in files:
                file_path = os.path.join(root, FILE_NAME)
                found_any_data = True
                
                print(f"Aggregating data from: {dir_name} (Threshold: {threshold_value})")

                try:
                    df = pd.read_csv(file_path)
                    df.columns = ['Julian_Day', 'Station', 'Datetime', 'Probability', 'Amp', 'Wave_Type']

                    df_p = df[df['Wave_Type'] == 'p']['Probability']
                    df_s = df[df['Wave_Type'] == 's']['Probability']

                    num_p = len(df_p)
                    num_s = len(df_s)
                    
                    mean_p = df_p.mean() if num_p > 0 else 0.0
                    std_p = df_p.std() if num_p > 1 else 0.0 
                    mean_s = df_s.mean() if num_s > 0 else 0.0
                    std_s = df_s.std() if num_s > 1 else 0.0
                    
                    std_p = 0.0 if np.isnan(std_p) else std_p
                    std_s = 0.0 if np.isnan(std_s) else std_s

                    plot_data.append({
                        'threshold': threshold_value,
                        'num_p': num_p,
                        'num_s': num_s,
                        'mean_p': mean_p,
                        'std_p': std_p,
                        'mean_s': mean_s,
                        'std_s': std_s,
                    })

                except Exception as e:
                    print(f"ERROR: Could not process file in {root}. Details: {e}")
                
    if not found_any_data:
        print("\n--- NO DATA FOUND ---")
        print(f"Could not find '{FILE_NAME}' in any subdirectory starting with 'output_picks_' under '{BASE_DIRECTORY}'.")
        return

    df_plot = pd.DataFrame(plot_data)
    df_plot['threshold_num'] = pd.to_numeric(df_plot['threshold'], errors='coerce') 
    df_plot = df_plot.sort_values(by='threshold_num', na_position='last')
    
    with open(log_path, 'w') as log_file:
        log_file.write("=== Probability Analysis by Threshold ===\n\n")
        log_file.write(
            "Threshold\tCount P\tCount S\tMean Prob P\tStd Dev Prob P\tMean Prob S\tStd Dev Prob S\n"
            "------------------------------------------------------------------------------------------------------\n"
        )
        for index, row in df_plot.iterrows():
            log_entry = (
                f"{row['threshold']}\t{row['num_p']}\t{row['num_s']}\t{row['mean_p']:.4f}\t{row['std_p']:.4f}\t{row['mean_s']:.4f}\t{row['std_s']:.4f}\n"
            )
            log_file.write(log_entry)
        
    generate_combined_plots(df_plot, BASE_DIRECTORY)
    
    print(f"\nAnalysis complete!")
    print(f"Single log file saved (SORTED) to: {log_path}")
    print(f"Single combined PDF saved to: {os.path.join(BASE_DIRECTORY, SINGLE_PDF_FILE)}")


if __name__ == '__main__':
    run_sort_picks()
    analyze_data_by_threshold()
