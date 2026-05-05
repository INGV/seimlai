#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 23 11:09:52 2026

@author: rossella.fonzetti
"""
import os
import pandas as pd
import numpy as np
import obspy
from obspy.signal.cross_correlation import xcorr_pick_correction
from obspy.geodetics import gps2dist_azimuth
from tqdm import tqdm
from config import (root_dir, dd_dir, dd_output_file, dd_dtcc_file,
                    MAX_DIST_KM_CC, CC_THRESHOLD_11, WIN_BEFORE_CC,
                    WIN_AFTER_CC, CC_MAX_LAG_11, FREQ_MIN_CC, FREQ_MAX_CC,
                    CC_NETWORK)

# --- CONFIGURAZIONE PERCORSI (from config.py) ---
WAVEFORM_DIR = root_dir
FILE_TRAVEL = dd_output_file
OUTPUT_DTCC = dd_dtcc_file

# --- PARAMETRI ---
MAX_DIST_KM = MAX_DIST_KM_CC
CC_THRESHOLD = CC_THRESHOLD_11
WIN_BEFORE = WIN_BEFORE_CC
WIN_AFTER = WIN_AFTER_CC
CC_MAX_LAG = CC_MAX_LAG_11
FREQ_MIN = FREQ_MIN_CC
FREQ_MAX = FREQ_MAX_CC

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

def get_waveform(sta, time, phase, network=CC_NETWORK):
    """Carica waveform seguendo lo screenshot: YEAR/NET/STA/CHAN.D/NET.STA..CHAN.D.YEAR.JDAY"""
    year = str(time.year)
    jday = time.strftime("%j")
    # P su Z, S su E (come da screenshot MZ05 ha EHE, EHN, EHZ)
    chan = f"EH{'Z' if phase == 'P' else 'E'}"
    
    path = os.path.join(WAVEFORM_DIR, year, network, sta, f"{chan}.D", 
                        f"{network}.{sta}..{chan}.D.{year}.{jday}")
    
    if os.path.exists(path):
        try:
            st = obspy.read(path)
            st.detrend("demean").filter("bandpass", freqmin=FREQ_MIN, freqmax=FREQ_MAX)
            return st[0]
        except: return None
    return None

# --- MAIN ---

print(f"Lettura travel.dat: {os.path.basename(FILE_TRAVEL)}")
catalog = parse_travel_dat(FILE_TRAVEL)
event_ids = sorted(catalog.keys())

print(f"Calcolo CC su {len(event_ids)} eventi selezionati...")

with open(OUTPUT_DTCC, "w") as f_out:
    for i in tqdm(range(len(event_ids)), desc="Loop Eventi"):
        id1 = event_ids[i]
        ev1 = catalog[id1]
        
        for j in range(i + 1, len(event_ids)):
            id2 = event_ids[j]
            ev2 = catalog[id2]
            
            # 1. Filtro Distanza
            dist_m, _, _ = gps2dist_azimuth(ev1['lat'], ev1['lon'], ev2['lat'], ev2['lon'])
            if dist_m / 1000.0 > MAX_DIST_KM: continue
            
            header_written = False
            
            # 2. Trova stazioni/fasi comuni
            picks1 = { (p['sta'], p['phase']): p['tt'] for p in ev1['picks'] }
            picks2 = { (p['sta'], p['phase']): p['tt'] for p in ev2['picks'] }
            common = set(picks1.keys()) & set(picks2.keys())
            
            for sta, phase in common:
                # Tempi di arrivo assoluti: Origin Time + Travel Time
                t1 = ev1['ot'] + picks1[(sta, phase)]
                t2 = ev2['ot'] + picks2[(sta, phase)]
                
                tr1 = get_waveform(sta, t1, phase)
                tr2 = get_waveform(sta, t2, phase)
                
                if tr1 and tr2:
                    try:
                        shift, cc_val = xcorr_pick_correction(
                            t1, tr1, t2, tr2, WIN_BEFORE, WIN_AFTER, CC_MAX_LAG
                        )
                        
                        if cc_val >= CC_THRESHOLD:
                            if not header_written:
                                f_out.write(f"# {id1:>9} {id2:>9} 0.0\n")
                                header_written = True
                            
                            dt_cc = (t1 - t2) - shift
                            f_out.write(f"{sta:<5} {dt_cc:10.4f} {cc_val:7.4f} {phase}\n")
                    except: continue

print(f"Fatto! File dt.cc generato in {dd_dir}")