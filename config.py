#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration file for all scripts.
Contains environment variables, paths, and parameters shared across the pipeline.
"""

import os
from obspy import UTCDateTime
from obspy.clients.fdsn import Client
import torch
from seisbench.models import PhaseNet

# ==========================================
# 1. USER CONFIGURATION
# ==========================================

# === Case Study ===
case_study_name = "Amatrice_catalog"

# === Geographic Bounding Box ===
minlatitude = 42.25
maxlatitude = 43.12
minlongitude = 11.75
maxlongitude = 14.00

# === Time Interval ===
starttime = UTCDateTime("2016-11-01")
endtime = UTCDateTime("2016-11-03")
year = 2016

# === Station Parameters ===
network = "YR"                # network code
channel = "BH?,HH?,EH?"      # channel types
stations_list = "*"

# === FDSN Clients ===
# fdsn_clients = [Client("INGV"), Client("IRIS")]
fdsn_clients = [Client("IRIS")]

# === Picking Parameters ===
BATCH_SIZE = 256
P_THRESHOLD = 0.9
S_THRESHOLD = 0.9

# === Plotting Parameters ===
# LUNGHEZZA DELLA FINESTRA DI VISUALIZZAZIONE PER SUBPLOT (in secondi)
WLENGTH_SECONDS = 900 # 30 min


# =====================================================================
# 2. SYSTEM VARIABLES (Automatically derived)
# =====================================================================

# === Time Interval (Derived) ===
# Days corresponding to the interval
start_day = starttime.julday
end_day = endtime.julday

# === Directory Paths ===
base_dir = os.getcwd()
case_study_dir = os.path.join(base_dir, case_study_name)
inventory_dir = os.path.join(base_dir, case_study_name, "inventory")
download_log_path = os.path.join(base_dir, case_study_name, "download_log.txt")  # used by script 01

# --- SETUP DIRECTORIES CONTAINING THE OUTPUTS OF THE SCRIPTS ---
root_dir = os.path.join(base_dir, case_study_name, "waveforms")  
waveform_base = os.path.join(root_dir, str(year))  # where script 02+ reads from
output_base = os.path.join(base_dir, case_study_name, "output")
output_picks_dir = os.path.join(output_base, f"output_picks_{P_THRESHOLD}")
plot_dir = os.path.join(output_base, "plots_annotations", f"{year}_{start_day:03d}_{end_day:03d}")
log_file_path = os.path.join(output_base, "phase_picking_log.txt")  # used by scripts 02+

# === Device Configuration ===
# --- CONFIGURAZIONE DEVICE (GPU/MPS/CPU) ---
if torch.backends.mps.is_available():
    device = torch.device("mps")
    device_name = "MPS (Apple Silicon GPU)"
elif torch.cuda.is_available():
    device = torch.device("cuda")
    device_name = torch.cuda.get_device_name(0)
else:
    device = torch.device("cpu")
    device_name = "CPU"

# --- CARICAMENTO MODELLO ---
model = PhaseNet.from_pretrained('original')
