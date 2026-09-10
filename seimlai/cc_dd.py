#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a HypoDD ``dt.cc`` file using GPU or CPU cross-correlations.

``cc_dd.use_gpu: true`` uses CUDA or Apple MPS.  With ``false`` the identical
normalised-correlation algorithm runs on CPU, which is slower but fully usable.
"""

import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from glob import glob

import numpy as np
from scipy.spatial import cKDTree
import obspy
import torch
import torch.nn.functional as torch_functional
from obspy.geodetics import gps2dist_azimuth
from tqdm import tqdm


WAVEFORM_DIR = None
FILE_TRAVEL = None
OUTPUT_DTCC = None

MAX_DIST_KM = None
CC_THRESHOLD = None
CC_SNR_THRESHOLD = None
CC_MIN_COMMON_PICKS_PER_PAIR = None
CC_MIN_READINGS_PER_PAIR = None
CC_MAX_ABS_DT_SECONDS = None
CC_MAX_NEIGHBORS = None
FREQ_MIN = None
FREQ_MAX = None
FILTER_PAD_SECONDS = None
CC_NETWORK = None
CC_GPU_BATCH_SIZE = None
CC_USE_GPU = None
CC_WORKER_COUNT = None
CC_CHUNK_SIZE = None
CC_P_CHANNEL = None
CC_S_E_CHANNEL = None
CC_S_N_CHANNEL = None
CC_REQUIRE_BOTH_S_COMPONENTS = None
P_WIN_BEFORE = None
P_WIN_AFTER = None
P_MAX_LAG = None
S_WIN_BEFORE = None
S_WIN_AFTER = None
S_MAX_LAG = None
CC_PEAK_EDGE_MARGIN_SECONDS = None
CC_S_SHIFT_TOLERANCE_SECONDS = None


def _cfg_value(cfg, name, default=None):
    """Read a value from either a dict or the workflow configuration object."""
    try:
        return cfg[name]
    except (KeyError, TypeError):
        return getattr(cfg, name, default)


def _apply_context(ctx):
    """Load paths plus every CC parameter from ``config.yaml``.

    The old generic ``win_before/win_after/cc_max_lag`` variables are not used:
    P and S now have independent windows and lag limits.
    """
    globals().update(ctx.legacy_globals(include_device=True))
    cfg = ctx.raw.cc_dd
    globals().update({
        "WAVEFORM_DIR": root_dir,
        "FILE_TRAVEL": dd_output_file,
        "OUTPUT_DTCC": dd_dtcc_file,
        "MAX_DIST_KM": float(_cfg_value(cfg, "max_dist_km_cc")),
        "CC_THRESHOLD": float(_cfg_value(cfg, "cc_threshold")),
        "CC_SNR_THRESHOLD": float(_cfg_value(cfg, "snr_threshold", 0.0)),
        "CC_MIN_COMMON_PICKS_PER_PAIR": int(
            _cfg_value(cfg, "min_common_picks_per_pair", 1)
        ),
        "CC_MIN_READINGS_PER_PAIR": int(
            _cfg_value(cfg, "min_readings_per_pair", 1)
        ),
        "CC_MAX_ABS_DT_SECONDS": float(
            _cfg_value(cfg, "max_abs_dt_seconds", 2.0)
        ),
        "CC_MAX_NEIGHBORS": int(_cfg_value(cfg, "max_neighbors", 20)),
        "FREQ_MIN": float(_cfg_value(cfg, "freq_min")),
        "FREQ_MAX": float(_cfg_value(cfg, "freq_max")),
        "FILTER_PAD_SECONDS": float(_cfg_value(cfg, "filter_pad_seconds", 1.0)),
        "CC_NETWORK": str(_cfg_value(cfg, "network", "*")).upper(),
        "CC_GPU_BATCH_SIZE": _cfg_value(cfg, "gpu_batch_size", "auto"),
        "CC_USE_GPU": bool(_cfg_value(cfg, "use_gpu", False)),
        "CC_WORKER_COUNT": _cfg_value(cfg, "worker_count", None),
        "CC_CHUNK_SIZE": _cfg_value(cfg, "chunk_size", None),
        "CC_P_CHANNEL": str(_cfg_value(cfg, "p_channel", "??Z")).upper(),
        "CC_S_E_CHANNEL": str(_cfg_value(cfg, "s_e_channel", "??E")).upper(),
        "CC_S_N_CHANNEL": str(_cfg_value(cfg, "s_n_channel", "??N")).upper(),
        "CC_REQUIRE_BOTH_S_COMPONENTS": bool(
            _cfg_value(cfg, "require_both_s_components", True)
        ),
        "P_WIN_BEFORE": float(_cfg_value(cfg, "p_win_before")),
        "P_WIN_AFTER": float(_cfg_value(cfg, "p_win_after")),
        "P_MAX_LAG": float(_cfg_value(cfg, "p_max_lag")),
        "S_WIN_BEFORE": float(_cfg_value(cfg, "s_win_before")),
        "S_WIN_AFTER": float(_cfg_value(cfg, "s_win_after")),
        "S_MAX_LAG": float(_cfg_value(cfg, "s_max_lag")),
        "CC_PEAK_EDGE_MARGIN_SECONDS": float(
            _cfg_value(cfg, "peak_edge_margin_seconds", 0.0)
        ),
        "CC_S_SHIFT_TOLERANCE_SECONDS": float(
            _cfg_value(cfg, "s_shift_tolerance_seconds", 0.02)
        ),
    })


def parse_travel_dat(filepath):
    """Read ``travel.dat`` and return origin times, locations and picks."""
    catalog = {}
    current_id = None
    with open(filepath, "r") as f_in:
        for line in f_in:
            if not line.strip():
                continue
            if line.startswith("#"):
                fields = line.split()
                event_id = int(fields[-1])
                catalog[event_id] = {
                    "ot": obspy.UTCDateTime(
                        int(fields[1]), int(fields[2]), int(fields[3]),
                        int(fields[4]), int(fields[5]),
                    ) + float(fields[6]),
                    "lat": float(fields[7]),
                    "lon": float(fields[8]),
                    "picks": [],
                }
                current_id = event_id
            elif current_id is not None:
                fields = line.split()
                if len(fields) >= 4:
                    phase = fields[3].upper()
                    if phase in {"P", "S"}:
                        catalog[current_id]["picks"].append({
                            "sta": fields[0], "tt": float(fields[1]), "phase": phase,
                        })
    return catalog


def _waveform_priority(path):
    channel = os.path.basename(os.path.dirname(path)).removesuffix(".D")
    return ({"HH": 0, "EH": 1, "BH": 2}.get(channel[:2], 3), path)


def _matching_waveform_paths(station, pick_time, channel_pattern):
    year = str(pick_time.year)
    jday = pick_time.strftime("%j")
    pattern = os.path.join(
        WAVEFORM_DIR, year, CC_NETWORK, station, f"{channel_pattern}.D",
        f"{CC_NETWORK}.{station}..{channel_pattern}.D.{year}.{jday}",
    )
    return sorted(glob(pattern), key=_waveform_priority)


def _channel_code(path):
    return os.path.basename(os.path.dirname(path)).removesuffix(".D")


def _get_waveform_paths(station, pick_time, phase):
    """Return Z for P, or a coherent E/N pair for S.

    An S observation is accepted only if the two horizontal components have the
    same channel family (for example HHE and HHN).  This avoids mixing sensors.
    """
    if phase == "P":
        paths = _matching_waveform_paths(station, pick_time, CC_P_CHANNEL)
        return {"Z": paths[0]} if paths else None

    east = _matching_waveform_paths(station, pick_time, CC_S_E_CHANNEL)
    north = _matching_waveform_paths(station, pick_time, CC_S_N_CHANNEL)
    east_by_family = {_channel_code(path)[:2]: path for path in east}
    north_by_family = {_channel_code(path)[:2]: path for path in north}
    families = sorted(set(east_by_family) & set(north_by_family))
    if not families:
        return None
    family = sorted(families, key=lambda x: {"HH": 0, "EH": 1, "BH": 2}.get(x, 3))[0]
    return {"E": east_by_family[family], "N": north_by_family[family]}


def _window_spec(phase):
    if phase == "P":
        return P_WIN_BEFORE, P_WIN_AFTER, P_MAX_LAG
    return S_WIN_BEFORE, S_WIN_AFTER, S_MAX_LAG


def _prepare_pick_window(stream, pick_time, phase):
    """Filter one padded local trace, then return the correlation window and SNR."""
    before, after, max_lag = _window_spec(phase)
    core_start = pick_time - before - max_lag / 2.0
    core_end = pick_time + after + max_lag / 2.0
    read_start = core_start - FILTER_PAD_SECONDS
    read_end = core_end + FILTER_PAD_SECONDS
    trace = next(
        (candidate for candidate in stream
         if candidate.stats.starttime <= read_start and candidate.stats.endtime >= read_end),
        None,
    )
    if trace is None:
        return None
    local = trace.copy().slice(read_start, read_end)
    try:
        local.detrend("linear").detrend("demean")
        local.taper(max_percentage=0.05, type="cosine")
        local.filter("bandpass", freqmin=FREQ_MIN, freqmax=FREQ_MAX,
                     corners=4, zerophase=True)
    except Exception:
        return None
    data = np.asarray(local.slice(core_start, core_end).data, dtype=np.float32)
    if data.size < 3 or not np.isfinite(data).all():
        return None
    # Noise is the padded data immediately before the actual CC window.
    noise = np.asarray(local.slice(read_start, core_start).data, dtype=np.float64)
    signal = np.asarray(local.slice(pick_time - before, pick_time + after).data,
                        dtype=np.float64)
    if noise.size < 3 or signal.size < 3:
        return None
    noise_rms = np.sqrt(np.mean(noise ** 2))
    signal_rms = np.sqrt(np.mean(signal ** 2))
    snr = signal_rms / max(noise_rms, np.finfo(float).eps)
    return data.copy(), float(local.stats.sampling_rate), float(snr)


def _extract_pick_windows(catalog, pick_maps, debug_counts):
    """Read every daily file once and cache P-Z and S-E/N windows."""
    requests_by_path = defaultdict(list)
    for event_id, picks in pick_maps.items():
        event = catalog[event_id]
        for (station, phase), travel_time in picks.items():
            debug_counts[station]["catalog_picks"] += 1
            pick_time = event["ot"] + travel_time
            paths = _get_waveform_paths(station, pick_time, phase)
            if paths is None:
                debug_counts[station]["missing_waveform"] += 1
                continue
            for component, path in paths.items():
                requests_by_path[path].append(
                    ((event_id, station, phase, component), pick_time)
                )

    windows = {}
    print(f"Preloading {len(requests_by_path)} unique waveforms for the GPU...")
    for path, requests in tqdm(requests_by_path.items(), desc="Waveform GPU"):
        try:
            stream = obspy.read(path)
        except Exception:
            for (_, station, _, _), _ in requests:
                debug_counts[station]["read_error"] += 1
            continue
        for key, pick_time in requests:
            _, station, _, _ = key
            prepared = _prepare_pick_window(stream, pick_time, key[2])
            if prepared is None:
                debug_counts[station]["invalid_window"] += 1
                continue
            windows[key] = prepared
            debug_counts[station]["valid_window"] += 1
    return windows


def _gpu_correlate_batch(first, second, shift_len):
    """Normalized correlation, mathematically equivalent to ObsPy's discrete CC."""
    first_tensor = torch.as_tensor(np.stack(first), dtype=torch.float32, device=device)
    second_tensor = torch.as_tensor(np.stack(second), dtype=torch.float32, device=device)
    first_tensor -= first_tensor.mean(dim=1, keepdim=True)
    second_tensor -= second_tensor.mean(dim=1, keepdim=True)
    length_difference = first_tensor.shape[1] - second_tensor.shape[1] - 2 * shift_len
    if length_difference > 0:
        left = length_difference // 2
        second_tensor = torch_functional.pad(second_tensor, (left, length_difference - left))
    else:
        amount = -length_difference
        left = amount // 2
        first_tensor = torch_functional.pad(first_tensor, (left, amount - left))
    correlation = torch_functional.conv1d(
        first_tensor.unsqueeze(0), second_tensor.unsqueeze(1), groups=len(first)
    ).squeeze(0)
    norm = torch.sqrt(torch.sum(first_tensor ** 2, dim=1) *
                      torch.sum(second_tensor ** 2, dim=1))
    correlation = torch.where(norm[:, None] > np.finfo(np.float32).eps,
                              correlation / norm[:, None], torch.zeros_like(correlation))
    return correlation.cpu().numpy()


def _refine_peak(correlation, shift_len, sampling_rate, max_lag):
    """Use only the three samples around the maximum for sub-sample timing.

    The returned coefficient is the *measured* normalized correlation maximum,
    never the value of a polynomial extrapolated across a broad peak.
    """
    cc = np.asarray(correlation, dtype=np.float64)
    index = int(np.argmax(cc))
    if not np.isfinite(cc[index]) or index == 0 or index == len(cc) - 1:
        raise ValueError("CC maximum is at the edge")
    y_left, y_peak, y_right = cc[index - 1:index + 2]
    denominator = y_left - 2.0 * y_peak + y_right
    fraction = 0.0 if abs(denominator) < np.finfo(float).eps else \
        0.5 * (y_left - y_right) / denominator
    if not np.isfinite(fraction) or abs(fraction) > 1.0:
        raise ValueError("invalid sub-sample CC peak")
    correlation_lag = (index - shift_len + fraction) / sampling_rate
    correction = -correlation_lag  # Same sign convention as xcorr_pick_correction.
    if abs(correction) > max_lag - CC_PEAK_EDGE_MARGIN_SECONDS:
        raise ValueError("CC maximum reaches the permitted lag edge")
    return correction, float(y_peak)


def _get_gpu_batch_size(job_count):
    if str(CC_GPU_BATCH_SIZE).lower() != "auto":
        value = int(CC_GPU_BATCH_SIZE)
        if value <= 0:
            raise ValueError("cc_dd.gpu_batch_size must be 'auto' or a positive integer")
        return min(value, max(job_count, 1))
    if device.type == "cuda":
        default = 4096
    elif device.type == "mps":
        default = 2048
    else:
        # Limit RAM consumption on ordinary CPU-only computers.
        default = 128
    return min(default, max(job_count, 1))


def _add_job(groups, job):
    first, second, rate, _, _, max_lag = job[-6:]
    if first.shape != second.shape:
        return False
    shift_len = int(round(max_lag * rate))
    if shift_len < 1:
        return False
    groups[(len(first), len(second), shift_len)].append(job)
    return True


def _build_gpu_jobs(tasks, pick_maps, windows, debug_counts):
    p_groups = defaultdict(list)
    s_groups = defaultdict(list)
    for task_index, id1, id2 in tasks:
        common = sorted(set(pick_maps[id1]) & set(pick_maps[id2]))
        for station, phase in common:
            debug_counts[station]["candidate_pairs"] += 1
            tt1, tt2 = pick_maps[id1][(station, phase)], pick_maps[id2][(station, phase)]
            if phase == "P":
                first = windows.get((id1, station, phase, "Z"))
                second = windows.get((id2, station, phase, "Z"))
                if first is None or second is None:
                    debug_counts[station]["unavailable_pairs"] += 1
                    continue
                a, rate_a, snr_a = first
                b, rate_b, snr_b = second
                if rate_a != rate_b or min(snr_a, snr_b) < CC_SNR_THRESHOLD:
                    debug_counts[station]["snr_or_rate_rejected"] += 1
                    continue
                if _add_job(p_groups, (task_index, id1, id2, station, tt1, tt2,
                                       a, b, rate_a, P_WIN_BEFORE, P_WIN_AFTER, P_MAX_LAG)):
                    debug_counts[station]["correlation_jobs"] += 1
                continue

            e1, e2 = windows.get((id1, station, phase, "E")), windows.get((id2, station, phase, "E"))
            n1, n2 = windows.get((id1, station, phase, "N")), windows.get((id2, station, phase, "N"))
            if None in (e1, e2, n1, n2):
                debug_counts[station]["unavailable_pairs"] += 1
                continue
            e_a, e_rate_a, e_snr_a = e1
            e_b, e_rate_b, e_snr_b = e2
            n_a, n_rate_a, n_snr_a = n1
            n_b, n_rate_b, n_snr_b = n2
            if len({e_rate_a, e_rate_b, n_rate_a, n_rate_b}) != 1 or \
                    min(e_snr_a, e_snr_b, n_snr_a, n_snr_b) < CC_SNR_THRESHOLD:
                debug_counts[station]["snr_or_rate_rejected"] += 1
                continue
            # The E and N curves are kept together and averaged after GPU CC.
            if e_a.shape != e_b.shape or e_a.shape != n_a.shape or e_a.shape != n_b.shape:
                debug_counts[station]["snr_or_rate_rejected"] += 1
                continue
            shift_len = int(round(S_MAX_LAG * e_rate_a))
            if shift_len < 1:
                continue
            s_groups[(len(e_a), len(e_b), shift_len)].append(
                (task_index, id1, id2, station, tt1, tt2, e_a, e_b, n_a, n_b, e_rate_a)
            )
            debug_counts[station]["correlation_jobs"] += 1
    return p_groups, s_groups


def _accept_reading(pair_readings, task_index, id1, id2, station, phase, tt1, tt2,
                    correction, coefficient, debug_counts):
    if coefficient < CC_THRESHOLD:  # Positive CC only: do not use abs(CC).
        debug_counts[station]["below_threshold"] += 1
        return
    dt_cc = (tt1 - tt2) - correction
    if abs(dt_cc) > CC_MAX_ABS_DT_SECONDS:
        debug_counts[station]["invalid_dt"] += 1
        return
    debug_counts[station]["accepted"] += 1
    pair_readings[task_index].append(
        f"{station:<5} {dt_cc:10.4f} {coefficient:7.4f} {phase}\n"
    )


def _run_gpu_correlations(tasks, catalog, pick_maps, debug_counts):
    windows = _extract_pick_windows(catalog, pick_maps, debug_counts)
    p_groups, s_groups = _build_gpu_jobs(tasks, pick_maps, windows, debug_counts)
    job_count = sum(map(len, p_groups.values())) + sum(map(len, s_groups.values()))
    batch_size = _get_gpu_batch_size(job_count)
    pair_readings = [[] for _ in tasks]
    processor = "GPU" if device.type in {"cuda", "mps"} else "CPU"
    print(f"Correlating {job_count} P/S station pairs on {device_name} ({device}); "
          f"{processor} batch size: {batch_size}.")

    with tqdm(total=job_count, desc=f"CC {processor}") as progress:
        for (_, _, shift_len), jobs in p_groups.items():
            for start in range(0, len(jobs), batch_size):
                batch = jobs[start:start + batch_size]
                curves = _gpu_correlate_batch([x[6] for x in batch], [x[7] for x in batch], shift_len)
                for job, curve in zip(batch, curves):
                    task, id1, id2, station, tt1, tt2, _, _, rate, _, _, lag = job
                    try:
                        correction, coefficient = _refine_peak(curve, shift_len, rate, lag)
                    except ValueError:
                        debug_counts[station]["peak_rejected"] += 1
                        continue
                    _accept_reading(pair_readings, task, id1, id2, station, "P", tt1, tt2,
                                    correction, coefficient, debug_counts)
                progress.update(len(batch))

        for (_, _, shift_len), jobs in s_groups.items():
            for start in range(0, len(jobs), batch_size):
                batch = jobs[start:start + batch_size]
                e_curves = _gpu_correlate_batch([x[6] for x in batch], [x[7] for x in batch], shift_len)
                n_curves = _gpu_correlate_batch([x[8] for x in batch], [x[9] for x in batch], shift_len)
                for job, e_curve, n_curve in zip(batch, e_curves, n_curves):
                    task, id1, id2, station, tt1, tt2, *_rest, rate = job
                    try:
                        e_shift, _ = _refine_peak(e_curve, shift_len, rate, S_MAX_LAG)
                        n_shift, _ = _refine_peak(n_curve, shift_len, rate, S_MAX_LAG)
                        if abs(e_shift - n_shift) > CC_S_SHIFT_TOLERANCE_SECONDS:
                            raise ValueError("E/N S shifts are inconsistent")
                        correction, coefficient = _refine_peak(
                            0.5 * (e_curve + n_curve), shift_len, rate, S_MAX_LAG
                        )
                    except ValueError:
                        debug_counts[station]["peak_rejected"] += 1
                        continue
                    _accept_reading(pair_readings, task, id1, id2, station, "S", tt1, tt2,
                                    correction, coefficient, debug_counts)
                progress.update(len(batch))

    if device.type == "cuda":
        torch.cuda.synchronize()
        torch.cuda.empty_cache()
    elif device.type == "mps":
        torch.mps.synchronize()
        torch.mps.empty_cache()

    with open(OUTPUT_DTCC, "w") as f_out:
        for (_, id1, id2), readings in zip(tasks, pair_readings):
            if len(readings) >= CC_MIN_READINGS_PER_PAIR:
                f_out.write(f"# {id1:>9} {id2:>9} 0.0\n")
                f_out.writelines(readings)


_CPU_CATALOG = None
_CPU_PICK_MAPS = None


def _load_pick_components(station, pick_time, phase):
    """Load one P-Z or S-E/N observation for the CPU worker."""
    paths = _get_waveform_paths(station, pick_time, phase)
    if paths is None:
        return None
    components = {}
    for component, path in paths.items():
        try:
            stream = obspy.read(path)
        except Exception:
            return None
        prepared = _prepare_pick_window(stream, pick_time, phase)
        if prepared is None:
            return None
        components[component] = prepared
    return components


def _cpu_correlate(first, second, shift_len):
    """CPU implementation of the same normalised discrete CC used on GPU."""
    first = np.asarray(first, dtype=np.float64).copy()
    second = np.asarray(second, dtype=np.float64).copy()
    first -= first.mean()
    second -= second.mean()
    length_difference = len(first) - len(second) - 2 * shift_len
    if length_difference > 0:
        left = length_difference // 2
        second = np.pad(second, (left, length_difference - left))
    else:
        amount = -length_difference
        left = amount // 2
        first = np.pad(first, (left, amount - left))
    norm = np.sqrt(np.sum(first ** 2) * np.sum(second ** 2))
    if norm <= np.finfo(float).eps:
        raise ValueError("zero-energy correlation window")
    return np.correlate(first, second, mode="valid") / norm


def _cpu_accept_line(lines, id1, id2, station, phase, tt1, tt2,
                     correction, coefficient, debug_counts):
    if coefficient < CC_THRESHOLD:
        debug_counts[station]["below_threshold"] += 1
        return
    dt_cc = (tt1 - tt2) - correction
    if abs(dt_cc) > CC_MAX_ABS_DT_SECONDS:
        debug_counts[station]["invalid_dt"] += 1
        return
    debug_counts[station]["accepted"] += 1
    lines.append(f"{station:<5} {dt_cc:10.4f} {coefficient:7.4f} {phase}\n")


def _process_event_pair_cpu(task):
    """Calculate every common station/phase for one event pair in one CPU process."""
    _, id1, id2 = task
    event1, event2 = _CPU_CATALOG[id1], _CPU_CATALOG[id2]
    picks1, picks2 = _CPU_PICK_MAPS[id1], _CPU_PICK_MAPS[id2]
    lines = []
    counts = defaultdict(Counter)
    for station, phase in sorted(set(picks1) & set(picks2)):
        counts[station]["candidate_pairs"] += 1
        tt1, tt2 = picks1[(station, phase)], picks2[(station, phase)]
        first = _load_pick_components(station, event1["ot"] + tt1, phase)
        second = _load_pick_components(station, event2["ot"] + tt2, phase)
        if first is None or second is None:
            counts[station]["unavailable_pairs"] += 1
            continue
        try:
            if phase == "P":
                data1, rate1, snr1 = first["Z"]
                data2, rate2, snr2 = second["Z"]
                if rate1 != rate2 or min(snr1, snr2) < CC_SNR_THRESHOLD:
                    counts[station]["snr_or_rate_rejected"] += 1
                    continue
                shift_len = int(round(P_MAX_LAG * rate1))
                curve = _cpu_correlate(data1, data2, shift_len)
                correction, coefficient = _refine_peak(curve, shift_len, rate1, P_MAX_LAG)
                _cpu_accept_line(lines, id1, id2, station, "P", tt1, tt2,
                                 correction, coefficient, counts)
            else:
                e1, e_rate1, e_snr1 = first["E"]
                e2, e_rate2, e_snr2 = second["E"]
                n1, n_rate1, n_snr1 = first["N"]
                n2, n_rate2, n_snr2 = second["N"]
                if len({e_rate1, e_rate2, n_rate1, n_rate2}) != 1 or \
                        min(e_snr1, e_snr2, n_snr1, n_snr2) < CC_SNR_THRESHOLD:
                    counts[station]["snr_or_rate_rejected"] += 1
                    continue
                if e1.shape != e2.shape or e1.shape != n1.shape or e1.shape != n2.shape:
                    counts[station]["snr_or_rate_rejected"] += 1
                    continue
                shift_len = int(round(S_MAX_LAG * e_rate1))
                e_curve = _cpu_correlate(e1, e2, shift_len)
                n_curve = _cpu_correlate(n1, n2, shift_len)
                e_shift, _ = _refine_peak(e_curve, shift_len, e_rate1, S_MAX_LAG)
                n_shift, _ = _refine_peak(n_curve, shift_len, e_rate1, S_MAX_LAG)
                if abs(e_shift - n_shift) > CC_S_SHIFT_TOLERANCE_SECONDS:
                    raise ValueError("E/N S shifts are inconsistent")
                correction, coefficient = _refine_peak(
                    0.5 * (e_curve + n_curve), shift_len, e_rate1, S_MAX_LAG
                )
                _cpu_accept_line(lines, id1, id2, station, "S", tt1, tt2,
                                 correction, coefficient, counts)
            counts[station]["correlation_jobs"] += 1
        except (KeyError, ValueError):
            counts[station]["peak_rejected"] += 1
    if len(lines) < CC_MIN_READINGS_PER_PAIR:
        lines = []
    return task[0], lines, {station: dict(value) for station, value in counts.items()}


def _cpu_worker_context():
    names = (
        "WAVEFORM_DIR", "MAX_DIST_KM", "CC_THRESHOLD", "CC_SNR_THRESHOLD",
        "CC_MIN_READINGS_PER_PAIR", "CC_MAX_ABS_DT_SECONDS", "FREQ_MIN", "FREQ_MAX",
        "FILTER_PAD_SECONDS", "CC_NETWORK", "CC_P_CHANNEL", "CC_S_E_CHANNEL",
        "CC_S_N_CHANNEL", "CC_REQUIRE_BOTH_S_COMPONENTS", "P_WIN_BEFORE", "P_WIN_AFTER",
        "P_MAX_LAG", "S_WIN_BEFORE", "S_WIN_AFTER", "S_MAX_LAG",
        "CC_PEAK_EDGE_MARGIN_SECONDS", "CC_S_SHIFT_TOLERANCE_SECONDS",
    )
    return {name: globals()[name] for name in names}


def _cpu_worker_init(catalog, pick_maps, worker_context):
    global _CPU_CATALOG, _CPU_PICK_MAPS
    globals().update(worker_context)
    _CPU_CATALOG = catalog
    _CPU_PICK_MAPS = pick_maps


def _process_event_pair_chunk_cpu(tasks):
    return [_process_event_pair_cpu(task) for task in tasks]


def _merge_debug_counts(target, source):
    for station, counts in source.items():
        target[station].update(counts)


def _get_cpu_worker_count(task_count):
    if CC_WORKER_COUNT is not None:
        return max(1, min(int(CC_WORKER_COUNT), task_count))
    env_count = os.environ.get("CC_DD_WORKERS") or os.environ.get("SLURM_CPUS_PER_TASK")
    if env_count:
        try:
            return max(1, min(int(env_count), task_count))
        except ValueError:
            pass
    return max(1, min(max(1, (os.cpu_count() or 2) - 1), task_count))


def _get_cpu_chunk_size(task_count, worker_count):
    if CC_CHUNK_SIZE is not None:
        return max(1, int(CC_CHUNK_SIZE))
    return max(1, min(50, task_count // max(worker_count * 8, 1) or 1))


def _run_cpu_correlations(tasks, catalog, pick_maps, debug_counts):
    """CPU fallback: retain parallel event-pair processing from the original code."""
    if not tasks:
        open(OUTPUT_DTCC, "w").close()
        return
    workers = _get_cpu_worker_count(len(tasks))
    chunk_size = _get_cpu_chunk_size(len(tasks), workers)
    chunks = [tasks[i:i + chunk_size] for i in range(0, len(tasks), chunk_size)]
    pending, next_index = {}, 0
    print(f"CPU CC on {len(tasks)} event pairs with {workers} process(es).")
    with open(OUTPUT_DTCC, "w") as f_out:
        context = _cpu_worker_context()
        if workers == 1:
            _cpu_worker_init(catalog, pick_maps, context)
            iterator = (_process_event_pair_chunk_cpu(chunk) for chunk in chunks)
            with tqdm(total=len(tasks), desc="CC CPU") as progress:
                for results in iterator:
                    progress.update(len(results))
                    for task_index, lines, counts in results:
                        _merge_debug_counts(debug_counts, counts)
                        f_out.writelines(lines)
        else:
            with ProcessPoolExecutor(
                max_workers=workers, initializer=_cpu_worker_init,
                initargs=(catalog, pick_maps, context),
            ) as executor, tqdm(total=len(tasks), desc="CC CPU") as progress:
                futures = [executor.submit(_process_event_pair_chunk_cpu, chunk) for chunk in chunks]
                for future in as_completed(futures):
                    results = future.result()
                    progress.update(len(results))
                    for task_index, lines, counts in results:
                        pending[task_index] = (lines, counts)
                    while next_index in pending:
                        lines, counts = pending.pop(next_index)
                        _merge_debug_counts(debug_counts, counts)
                        f_out.writelines(lines)
                        next_index += 1


def _write_station_log(ctx, debug_counts):
    station_counts = Counter()
    with open(OUTPUT_DTCC, "r") as f_in:
        for line in f_in:
            if line.strip() and not line.startswith("#"):
                station_counts[line.split()[0]] += 1
    lines = []
    for station in sorted(set(debug_counts) | set(station_counts)):
        counts = debug_counts[station]
        lines.append(
            f"{station}: picks={counts['catalog_picks']}, candidates={counts['candidate_pairs']}, "
            f"jobs={counts['correlation_jobs']}, accepted={counts['accepted']}, "
            f"dt.cc={station_counts[station]}, missing={counts['missing_waveform']}, "
            f"invalid_window={counts['invalid_window']}, snr/rate_rejected={counts['snr_or_rate_rejected']}, "
            f"cc_under_threshold={counts['below_threshold']}, peak_rejected={counts['peak_rejected']}, "
            f"invalid_dt={counts['invalid_dt']}"
        )
    log_path = os.path.join(str(ctx.paths.hypodd_output_dir), "cc_station_log")
    with open(log_path, "w") as f_out:
        f_out.write("Station final debug:\n" + "\n".join(lines) + ("\n" if lines else ""))
    print(f"Stations used in dt.cc ({len(station_counts)}): " +
          (", ".join(f"{s}({n})" for s, n in sorted(station_counts.items())) or "none"))
    print(f"Station log saved in {log_path}")

def _build_event_pair_tasks(event_ids, catalog, pick_maps):
    """
    Find a bounded number of nearby event pairs with a spatial index.

    A dense catalog can contain hundreds of millions of pairs within a fixed
    radius.  Keeping every such pair is both redundant for HypoDD and can
    exhaust RAM before a single waveform is correlated.  Each event therefore
    contributes at most ``CC_MAX_NEIGHBORS`` nearest neighbours within the
    configured radius. Pairs selected from either endpoint are de-duplicated,
    then their distance is verified geodetically.
    """
    earth_radius_km = 6371.0088

    latitudes = np.deg2rad([
        catalog[event_id]["lat"] for event_id in event_ids
    ])
    longitudes = np.deg2rad([
        catalog[event_id]["lon"] for event_id in event_ids
    ])

    coordinates = np.column_stack((
        earth_radius_km * np.cos(latitudes) * np.cos(longitudes),
        earth_radius_km * np.cos(latitudes) * np.sin(longitudes),
        earth_radius_km * np.sin(latitudes),
    ))

    tree = cKDTree(coordinates)

    # 1% margin prevents missing a pair because the tree uses a spherical
    # approximation; gps2dist_azimuth below remains the final exact test.
    search_radius_km = 2.0 * earth_radius_km * np.sin(
        (MAX_DIST_KM * 1.01) / (2.0 * earth_radius_km)
    )
    max_neighbors = min(CC_MAX_NEIGHBORS, max(len(event_ids) - 1, 0))
    if max_neighbors < 1:
        return []

    # ``query_pairs`` materialises every pair in the radius. In this catalog
    # that was >900 million rows (>100 GB once converted to Python tasks).
    # Querying k nearest neighbours keeps memory O(N * k), not O(number of
    # all nearby pairs).
    _, neighbor_indexes = tree.query(
        coordinates,
        k=max_neighbors + 1,  # includes each event itself at distance zero
        distance_upper_bound=search_radius_km,
    )
    neighbor_indexes = np.asarray(neighbor_indexes)
    if neighbor_indexes.ndim == 1:
        neighbor_indexes = neighbor_indexes[:, None]

    source_indexes = np.repeat(
        np.arange(len(event_ids), dtype=np.int64), neighbor_indexes.shape[1]
    )
    target_indexes = neighbor_indexes.reshape(-1).astype(np.int64, copy=False)
    valid = (target_indexes < len(event_ids)) & (target_indexes != source_indexes)
    source_indexes = source_indexes[valid]
    target_indexes = target_indexes[valid]

    low = np.minimum(source_indexes, target_indexes)
    high = np.maximum(source_indexes, target_indexes)
    # Compact integer keys make de-duplication much cheaper than a Python set
    # of millions of ``(event_1, event_2)`` tuples.
    pair_keys = np.unique(low * len(event_ids) + high)
    first_indexes = pair_keys // len(event_ids)
    second_indexes = pair_keys % len(event_ids)

    print(
        f"Spatial index selected {len(pair_keys)} nearest-neighbour candidate pairs "
        f"(at most {max_neighbors} neighbours per event) before exact distance "
        "and common-pick checks."
    )

    pick_key_sets = {
        event_id: set(pick_maps[event_id])
        for event_id in event_ids
    }

    tasks = []
    for index1, index2 in zip(first_indexes, second_indexes):
        id1 = event_ids[int(index1)]
        id2 = event_ids[int(index2)]

        if len(pick_key_sets[id1] & pick_key_sets[id2]) < CC_MIN_COMMON_PICKS_PER_PAIR:
            continue

        event1 = catalog[id1]
        event2 = catalog[id2]
        distance_m, _, _ = gps2dist_azimuth(
            event1["lat"], event1["lon"],
            event2["lat"], event2["lon"],
        )

        if distance_m / 1000.0 <= MAX_DIST_KM:
            tasks.append((len(tasks), id1, id2))

    return tasks

def run(ctx):
    _apply_context(ctx)
    if CC_USE_GPU and device.type not in {"cuda", "mps"}:
        raise RuntimeError(
            f"cc_dd.use_gpu is true, but the active device is {device!s}. "
            "Set use_gpu: false to run on CPU."
        )
    if not CC_USE_GPU:
        # Override a workflow default device, if necessary, for CPU-only users.
        globals()["device"] = torch.device("cpu")
        globals()["device_name"] = "CPU"
    if not 0.0 < CC_THRESHOLD <= 1.0:
        raise ValueError("cc_dd.cc_threshold must be in (0, 1].")
    if CC_MAX_NEIGHBORS < 1:
        raise ValueError("cc_dd.max_neighbors must be a positive integer.")
    if not (0.0 < FREQ_MIN < FREQ_MAX):
        raise ValueError("cc_dd.freq_min and freq_max are not valid.")

    print(f"Reading travel.dat: {os.path.basename(FILE_TRAVEL)}")
    catalog = parse_travel_dat(FILE_TRAVEL)
    event_ids = sorted(catalog)
    pick_maps = {
        event_id: {(p["sta"], p["phase"]): p["tt"] for p in catalog[event_id]["picks"]}
        for event_id in event_ids
    }
    tasks = _build_event_pair_tasks(event_ids, catalog, pick_maps)
    mode = "GPU" if CC_USE_GPU else "CPU"
    print(f"{mode} CC for {len(tasks)} event pairs within {MAX_DIST_KM:g} km.")
    debug_counts = defaultdict(Counter)
    if CC_USE_GPU:
        _run_gpu_correlations(tasks, catalog, pick_maps, debug_counts)
    else:
        _run_cpu_correlations(tasks, catalog, pick_maps, debug_counts)
    _write_station_log(ctx, debug_counts)
