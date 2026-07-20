#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 23 11:09:52 2026

@author: rossella.fonzetti
"""
import warnings
import os
from glob import glob
from concurrent.futures import ProcessPoolExecutor, as_completed
import pandas as pd
import numpy as np
import obspy
from obspy.signal.cross_correlation import xcorr_pick_correction
from obspy.geodetics import gps2dist_azimuth
from tqdm import tqdm

WAVEFORM_DIR = None
FILE_TRAVEL = None
OUTPUT_DTCC = None

# --- PARAMETRI ---
MAX_DIST_KM = None
CC_THRESHOLD = None
WIN_BEFORE = None
WIN_AFTER = None
CC_MAX_LAG = None
FREQ_MIN = None
FREQ_MAX = None
CC_NETWORK = None
CC_WORKER_COUNT = None
CC_CHUNK_SIZE = None
CC_P_CHANNEL = None
CC_S_CHANNEL = None
CC_MAX_ABS_DT_SECONDS = None
_WORKER_CATALOG = None
_WORKER_PICK_MAPS = None


def _apply_context(ctx):
    globals().update(ctx.legacy_globals())
    globals().update({
        "WAVEFORM_DIR": root_dir,
        "FILE_TRAVEL": dd_output_file,
        "OUTPUT_DTCC": dd_dtcc_file,
        "MAX_DIST_KM": MAX_DIST_KM_CC,
        "CC_THRESHOLD": CC_THRESHOLD_11,
        "WIN_BEFORE": WIN_BEFORE_CC,
        "WIN_AFTER": WIN_AFTER_CC,
        "CC_MAX_LAG": CC_MAX_LAG_11,
        "FREQ_MIN": FREQ_MIN_CC,
        "FREQ_MAX": FREQ_MAX_CC,
        "CC_NETWORK": CC_NETWORK,
        "CC_WORKER_COUNT": CC_WORKER_COUNT,
        "CC_CHUNK_SIZE": CC_CHUNK_SIZE,
        "CC_P_CHANNEL": CC_P_CHANNEL,
        "CC_S_CHANNEL": CC_S_CHANNEL,
        "CC_MAX_ABS_DT_SECONDS": CC_MAX_ABS_DT_SECONDS,
    })

# --- FUNZIONI DI SUPPORTO ---

def parse_travel_dat(filepath):
    """
    Parsa il file travel.dat per ricostruire il catalogo con tempi assoluti.
    Restituisce un dizionario: {event_id: {'info': ..., 'picks': [...]}}
    """
    catalog = {}
    current_id = None
    
    with open(filepath, 'r') as f:
        for line in f:
            if line.startswith('#'):
                parts = line.split()
                # Formato: # YYYY MM DD HH MI SS.SS LAT LON DEP ... ID
                ev_id = int(parts[-1])
                ot = obspy.UTCDateTime(int(parts[1]), int(parts[2]), int(parts[3]), 
                                     int(parts[4]), int(parts[5])) + float(parts[6])
                catalog[ev_id] = {
                    'ot': ot,
                    'lat': float(parts[7]),
                    'lon': float(parts[8]),
                    'picks': []
                }
                current_id = ev_id
            else:
                parts = line.split()
                # Formato: STA TravelTime Weight Phase
                catalog[current_id]['picks'].append({
                    'sta': parts[0],
                    'tt': float(parts[1]),
                    'phase': parts[3]
                })
    return catalog

def _waveform_priority(path):
    channel = os.path.basename(os.path.dirname(path)).removesuffix(".D")
    return ({"HH": 0, "EH": 1, "BH": 2}.get(channel[:2], 3), path)


def get_waveform(sta, time, phase, network=None):
    """Carica la waveform migliore che corrisponde ai pattern di network e canale."""
    network = str(CC_NETWORK if network is None else network).upper()
    year = str(time.year)
    jday = time.strftime("%j")
    chan = str(CC_P_CHANNEL if phase == 'P' else CC_S_CHANNEL).upper()
    
    path_pattern = os.path.join(WAVEFORM_DIR, year, network, sta, f"{chan}.D",
                                f"{network}.{sta}..{chan}.D.{year}.{jday}")
    matching_paths = sorted(glob(path_pattern), key=_waveform_priority)
    
    if matching_paths:
        try:
            st = obspy.read(matching_paths[0])
            st.detrend("demean").filter("bandpass", freqmin=FREQ_MIN, freqmax=FREQ_MAX)
            return st[0]
        except: return None
    return None

def _cc_worker_context():
    return {
        "WAVEFORM_DIR": WAVEFORM_DIR,
        "FILE_TRAVEL": FILE_TRAVEL,
        "OUTPUT_DTCC": OUTPUT_DTCC,
        "MAX_DIST_KM": MAX_DIST_KM,
        "CC_THRESHOLD": CC_THRESHOLD,
        "WIN_BEFORE": WIN_BEFORE,
        "WIN_AFTER": WIN_AFTER,
        "CC_MAX_LAG": CC_MAX_LAG,
        "FREQ_MIN": FREQ_MIN,
        "FREQ_MAX": FREQ_MAX,
        "CC_NETWORK": CC_NETWORK,
        "CC_WORKER_COUNT": CC_WORKER_COUNT,
        "CC_CHUNK_SIZE": CC_CHUNK_SIZE,
        "CC_P_CHANNEL": CC_P_CHANNEL,
        "CC_S_CHANNEL": CC_S_CHANNEL,
        "CC_MAX_ABS_DT_SECONDS": CC_MAX_ABS_DT_SECONDS,
    }

def _cc_worker_init(catalog, pick_maps, worker_context):
    global _WORKER_CATALOG, _WORKER_PICK_MAPS
    globals().update(worker_context)
    _WORKER_CATALOG = catalog
    _WORKER_PICK_MAPS = pick_maps
    warnings.filterwarnings(
        "ignore",
        message="Maximum of cross correlation lower than*"
    )

def _process_event_pair(task):
    task_index, id1, id2 = task
    ev1 = _WORKER_CATALOG[id1]
    ev2 = _WORKER_CATALOG[id2]
    picks1 = _WORKER_PICK_MAPS[id1]
    picks2 = _WORKER_PICK_MAPS[id2]
    lines = []
    warnings_out = []
    header_written = False

    common = sorted(set(picks1.keys()) & set(picks2.keys()))
    for sta, phase in common:
        # Tempi di arrivo assoluti: Origin Time + Travel Time
        tt1 = picks1[(sta, phase)]
        tt2 = picks2[(sta, phase)]
        t1 = ev1['ot'] + tt1
        t2 = ev2['ot'] + tt2

        tr1 = get_waveform(sta, t1, phase)
        tr2 = get_waveform(sta, t2, phase)

        if tr1 and tr2:
            try:
                shift, cc_val = xcorr_pick_correction(
                    t1, tr1, t2, tr2, WIN_BEFORE, WIN_AFTER, CC_MAX_LAG,
                )

                if cc_val >= CC_THRESHOLD:
                    dt_cc = (tt1 - tt2) - shift
                    # Controllo di sicurezza: scarta valori non fisici.
                    if abs(dt_cc) > CC_MAX_ABS_DT_SECONDS:
                        warnings_out.append(
                            f"[WARN] dt.cc sospetto scartato: "
                            f"ev {id1}-{id2}, {sta} {phase}, "
                            f"tt1={tt1:.4f}, tt2={tt2:.4f}, "
                            f"shift={shift:.4f}, dt_cc={dt_cc:.4f}"
                        )
                        continue
                    if not header_written:
                        lines.append(f"# {id1:>9} {id2:>9} 0.0\n")
                        header_written = True
                    lines.append(f"{sta:<5} {dt_cc:10.4f} {cc_val:7.4f} {phase}\n")
            except Exception as exc:
                warnings_out.append(f"[WARN] CC fallita: ev {id1}-{id2}, {sta} {phase}: {exc}")
            continue

    reading_count = len(lines) - 1 if header_written else 0
    if reading_count < 4:
        lines = []

    return task_index, lines, warnings_out

def _process_event_pair_chunk(tasks):
    return [_process_event_pair(task) for task in tasks]

def _get_cc_worker_count(task_count):
    if CC_WORKER_COUNT is not None:
        return max(1, min(int(CC_WORKER_COUNT), task_count))
    worker_count = os.environ.get("CC_DD_WORKERS") or os.environ.get("SLURM_CPUS_PER_TASK")
    if worker_count:
        try:
            return max(1, min(int(worker_count), task_count))
        except ValueError:
            pass
    default_workers = max(1, int(((os.cpu_count() or 2) - 1) * 0.75))
    return max(1, min(default_workers, task_count))

def _get_cc_chunk_size(task_count, num_workers):
    if CC_CHUNK_SIZE is not None:
        return max(1, int(CC_CHUNK_SIZE))
    chunk_size = os.environ.get("CC_DD_CHUNK_SIZE")
    if chunk_size:
        try:
            return max(1, int(chunk_size))
        except ValueError:
            pass
    return max(1, min(50, task_count // max(num_workers * 8, 1) or 1))

def run(ctx):
    _apply_context(ctx)

    print(f"Lettura travel.dat: {os.path.basename(FILE_TRAVEL)}")
    catalog = parse_travel_dat(FILE_TRAVEL)
    event_ids = sorted(catalog.keys())

    print(f"Calcolo CC su {len(event_ids)} eventi selezionati...")
    warnings.filterwarnings(
        "ignore",
        message="Maximum of cross correlation lower than*"
    )
    pick_maps = {
        ev_id: { (p['sta'], p['phase']): p['tt'] for p in catalog[ev_id]['picks'] }
        for ev_id in event_ids
    }
    tasks = []
    task_index = 0
    for i in range(len(event_ids)):
        id1 = event_ids[i]
        ev1 = catalog[id1]

        for j in range(i + 1, len(event_ids)):
            id2 = event_ids[j]
            ev2 = catalog[id2]

            # 1. Filtro Distanza
            dist_m, _, _ = gps2dist_azimuth(ev1['lat'], ev1['lon'], ev2['lat'], ev2['lon'])
            if dist_m / 1000.0 > MAX_DIST_KM:
                continue
            tasks.append((task_index, id1, id2))
            task_index += 1

    num_workers = _get_cc_worker_count(len(tasks)) if tasks else 1
    print(f"Esecuzione CC parallela con {num_workers} workers su {len(tasks)} coppie entro {MAX_DIST_KM} km...")

    with open(OUTPUT_DTCC, "w") as f_out:
        worker_context = _cc_worker_context()
        if num_workers == 1:
            _cc_worker_init(catalog, pick_maps, worker_context)
            for task in tqdm(tasks, desc="Loop Coppie"):
                _, lines, warnings_out = _process_event_pair(task)
                for msg in warnings_out:
                    print(msg)
                f_out.writelines(lines)
        else:
            chunk_size = _get_cc_chunk_size(len(tasks), num_workers)
            task_chunks = [tasks[i:i + chunk_size] for i in range(0, len(tasks), chunk_size)]
            pending_results = {}
            next_write = 0
            with ProcessPoolExecutor(
                max_workers=num_workers,
                initializer=_cc_worker_init,
                initargs=(catalog, pick_maps, worker_context),
            ) as executor:
                futures = [executor.submit(_process_event_pair_chunk, chunk) for chunk in task_chunks]

                with tqdm(total=len(tasks), desc="Loop Coppie") as progress:
                    for future in as_completed(futures):
                        results = future.result()
                        progress.update(len(results))
                        for task_index, lines, warnings_out in results:
                            pending_results[task_index] = (lines, warnings_out)

                        while next_write in pending_results:
                            lines, warnings_out = pending_results.pop(next_write)
                            for msg in warnings_out:
                                print(msg)
                            f_out.writelines(lines)
                            next_write += 1

    print(f"Fatto! File dt.cc generato in {dd_dir}")


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_cc_dd = run


if __name__ == "__main__":
    main()
