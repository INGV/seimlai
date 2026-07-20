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
import torch
import torch.nn.functional as torch_functional
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
CC_USE_GPU = None
CC_GPU_BATCH_SIZE = None
_WORKER_CATALOG = None
_WORKER_PICK_MAPS = None


def _apply_context(ctx):
    globals().update(ctx.legacy_globals(include_device=True))
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
        "CC_USE_GPU": CC_USE_GPU,
        "CC_GPU_BATCH_SIZE": CC_GPU_BATCH_SIZE,
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


def _get_waveform_path(sta, time, phase, network=None):
    network = str(CC_NETWORK if network is None else network).upper()
    year = str(time.year)
    jday = time.strftime("%j")
    chan = str(CC_P_CHANNEL if phase == 'P' else CC_S_CHANNEL).upper()
    
    path_pattern = os.path.join(WAVEFORM_DIR, year, network, sta, f"{chan}.D",
                                f"{network}.{sta}..{chan}.D.{year}.{jday}")
    matching_paths = sorted(glob(path_pattern), key=_waveform_priority)
    return matching_paths[0] if matching_paths else None


def get_waveform(sta, time, phase, network=None):
    """Carica la waveform migliore che corrisponde ai pattern di network e canale."""
    waveform_path = _get_waveform_path(sta, time, phase, network)
    if waveform_path is None:
        return None
    try:
        st = obspy.read(waveform_path)
        st.detrend("demean").filter("bandpass", freqmin=FREQ_MIN, freqmax=FREQ_MAX)
        return st[0]
    except Exception:
        return None


def _extract_pick_windows(catalog, pick_maps):
    requests_by_path = {}
    missing_waveforms = 0
    for event_id, picks in pick_maps.items():
        event = catalog[event_id]
        for (sta, phase), travel_time in picks.items():
            pick_time = event["ot"] + travel_time
            waveform_path = _get_waveform_path(sta, pick_time, phase)
            if waveform_path is None:
                missing_waveforms += 1
                continue
            requests_by_path.setdefault(waveform_path, []).append(
                ((event_id, sta, phase), pick_time)
            )

    windows = {}
    failed_windows = 0
    print(f"Precaricamento di {len(requests_by_path)} waveform uniche per la GPU...")
    for waveform_path, requests in tqdm(requests_by_path.items(), desc="Waveform GPU"):
        try:
            stream = obspy.read(waveform_path)
            stream.detrend("demean").filter("bandpass", freqmin=FREQ_MIN, freqmax=FREQ_MAX)
            trace = stream[0]
        except Exception:
            failed_windows += len(requests)
            continue

        for key, pick_time in requests:
            start = pick_time - WIN_BEFORE - (CC_MAX_LAG / 2.0)
            end = pick_time + WIN_AFTER + (CC_MAX_LAG / 2.0)
            if trace.stats.starttime > start or trace.stats.endtime < end:
                failed_windows += 1
                continue
            data = np.asarray(trace.slice(start, end).data, dtype=np.float32)
            if data.size < 3 or not np.isfinite(data).all():
                failed_windows += 1
                continue
            windows[key] = (data.copy(), float(trace.stats.sampling_rate))

    print(
        f"Finestre GPU pronte: {len(windows)}; "
        f"waveform mancanti: {missing_waveforms}; finestre non valide: {failed_windows}."
    )
    return windows


def _fit_correlation_peak(cc, shift_len=None):
    cc = np.asarray(cc, dtype=np.float64)
    if cc.size < 3 or not np.isfinite(cc).all():
        raise ValueError("correlazione non valida")

    cc_curvature = np.concatenate((np.zeros(1), np.diff(cc, 2), np.zeros(1)))
    peak_index = int(cc.argmax())
    first_sample = peak_index
    while first_sample > 0 and cc_curvature[first_sample - 1] <= 0:
        first_sample -= 1
    last_sample = peak_index
    while last_sample < len(cc) - 1 and cc_curvature[last_sample + 1] <= 0:
        last_sample += 1
    if last_sample - first_sample + 1 < 3:
        raise ValueError("meno di 3 campioni disponibili per il fit parabolico")

    if shift_len is None:
        shift_len = (len(cc) - 1) // 2
    cc_t = np.linspace(-CC_MAX_LAG, CC_MAX_LAG, shift_len * 2 + 1)
    coeffs = np.polyfit(
        cc_t[first_sample:last_sample + 1],
        cc[first_sample:last_sample + 1],
        deg=2,
    )
    if coeffs[0] == 0:
        raise ValueError("fit parabolico degenere")
    shift = coeffs[1] / (2.0 * coeffs[0])
    coefficient = (4 * coeffs[0] * coeffs[2] - coeffs[1] ** 2) / (4 * coeffs[0])
    return shift, coefficient


def _gpu_correlate_batch(first, second, shift_len):
    first_tensor = torch.as_tensor(np.stack(first), dtype=torch.float32, device=device)
    second_tensor = torch.as_tensor(np.stack(second), dtype=torch.float32, device=device)
    first_tensor -= first_tensor.mean(dim=1, keepdim=True)
    second_tensor -= second_tensor.mean(dim=1, keepdim=True)
    length_difference = first_tensor.shape[1] - second_tensor.shape[1] - 2 * shift_len
    if length_difference > 0:
        padding = length_difference // 2
        second_tensor = torch_functional.pad(second_tensor, (padding, padding))
    else:
        padding = (-length_difference) // 2
        first_tensor = torch_functional.pad(first_tensor, (padding, padding))
    correlation = torch_functional.conv1d(
        first_tensor.unsqueeze(0),
        second_tensor.unsqueeze(1),
        groups=len(first),
    ).squeeze(0)
    norm = torch.sqrt(
        torch.sum(first_tensor ** 2, dim=1) * torch.sum(second_tensor ** 2, dim=1)
    )
    valid = norm > np.finfo(float).eps
    correlation = torch.where(valid[:, None], correlation / norm[:, None], 0)
    return correlation.cpu().numpy()


def _build_gpu_jobs(tasks, catalog, pick_maps, windows):
    jobs_by_shape = {}
    for task_index, id1, id2 in tasks:
        picks1 = pick_maps[id1]
        picks2 = pick_maps[id2]
        for sta, phase in sorted(set(picks1) & set(picks2)):
            first = windows.get((id1, sta, phase))
            second = windows.get((id2, sta, phase))
            if first is None or second is None:
                continue
            first_data, first_rate = first
            second_data, second_rate = second
            if first_rate != second_rate:
                continue
            shift_len = int(CC_MAX_LAG * first_rate)
            shape = (len(first_data), len(second_data), shift_len)
            jobs_by_shape.setdefault(shape, []).append((
                task_index,
                id1,
                id2,
                sta,
                phase,
                picks1[(sta, phase)],
                picks2[(sta, phase)],
                first_data,
                second_data,
            ))
    return jobs_by_shape


def _get_gpu_batch_size(job_count):
    if str(CC_GPU_BATCH_SIZE).lower() != "auto":
        batch_size = int(CC_GPU_BATCH_SIZE)
        if batch_size <= 0:
            raise ValueError("cc_dd.gpu_batch_size must be 'auto' or a positive integer.")
        return min(batch_size, max(job_count, 1))

    if device.type == "cuda":
        batch_size = 4096
    else:
        batch_size = 2048
    return min(batch_size, max(job_count, 1))


def _run_gpu_correlations(tasks, catalog, pick_maps):
    windows = _extract_pick_windows(catalog, pick_maps)
    jobs_by_shape = _build_gpu_jobs(tasks, catalog, pick_maps, windows)
    job_count = sum(len(jobs) for jobs in jobs_by_shape.values())
    batch_size = _get_gpu_batch_size(job_count)
    pair_readings = [[] for _ in tasks]
    failure_count = 0
    print(
        f"Correlazione di {job_count} coppie di finestre su {device_name} ({device}); "
        f"batch GPU: {batch_size}."
    )

    with tqdm(total=job_count, desc=f"CC {device.type.upper()}") as progress:
        for (_, _, shift_len), jobs in jobs_by_shape.items():
            for start in range(0, len(jobs), batch_size):
                batch = jobs[start:start + batch_size]
                correlations = _gpu_correlate_batch(
                    [job[7] for job in batch],
                    [job[8] for job in batch],
                    shift_len,
                )
                for job, correlation in zip(batch, correlations):
                    task_index, id1, id2, sta, phase, tt1, tt2 = job[:7]
                    try:
                        shift, cc_val = _fit_correlation_peak(correlation, shift_len)
                    except ValueError:
                        failure_count += 1
                        continue
                    if cc_val < CC_THRESHOLD:
                        continue
                    dt_cc = (tt1 - tt2) - shift
                    if abs(dt_cc) > CC_MAX_ABS_DT_SECONDS:
                        print(
                            f"[WARN] dt.cc sospetto scartato: ev {id1}-{id2}, "
                            f"{sta} {phase}, tt1={tt1:.4f}, tt2={tt2:.4f}, "
                            f"shift={shift:.4f}, dt_cc={dt_cc:.4f}"
                        )
                        continue
                    pair_readings[task_index].append(
                        f"{sta:<5} {dt_cc:10.4f} {cc_val:7.4f} {phase}\n"
                    )
                progress.update(len(batch))

    if device.type == "mps":
        torch.mps.synchronize()
        torch.mps.empty_cache()
    elif device.type == "cuda":
        torch.cuda.synchronize()
        torch.cuda.empty_cache()

    with open(OUTPUT_DTCC, "w") as f_out:
        for task, readings in zip(tasks, pair_readings):
            if len(readings) < 4:
                continue
            _, id1, id2 = task
            f_out.write(f"# {id1:>9} {id2:>9} 0.0\n")
            f_out.writelines(readings)
    if failure_count:
        print(f"[WARN] Fit parabolico non riuscito per {failure_count} correlazioni.")

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

    gpu_enabled = bool(CC_USE_GPU) and device.type in {"mps", "cuda"}
    if gpu_enabled:
        _run_gpu_correlations(tasks, catalog, pick_maps)
    else:
        if CC_USE_GPU:
            print("GPU richiesta ma non disponibile: uso il fallback CPU.")
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

    print(f"Fatto! File dt.cc generato in {os.path.dirname(OUTPUT_DTCC)}")


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_cc_dd = run


if __name__ == "__main__":
    main()
