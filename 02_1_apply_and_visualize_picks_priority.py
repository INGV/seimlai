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
