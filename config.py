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
from pyproj import CRS, Transformer

# ==========================================
# 1. USER CONFIGURATION
# ==========================================

# === Case Study ===
case_study_name = "Amatrice_catalog"
#TODO: inserire la possibilità di scegliere la path dei cataloghi

# === Geographic Bounding Box ===
minlatitude = 42.25
maxlatitude = 43.12
minlongitude = 11.75
maxlongitude = 14.00

# === Time Interval ===
starttime = UTCDateTime("2016-10-31")
endtime = UTCDateTime("2016-10-31")
year = 2016

# === Station Parameters ===
network = "*"                # network code
channel = "BH?,HH?,EH?"      # channel types
stations_list = "*"
# fdsn_clients = ["INGV", "IRIS"]
fdsn_clients = ["IRIS"]

# === Picking Parameters ===
BATCH_SIZE = 256
P_THRESHOLD = 0.9
S_THRESHOLD = 0.9

# === Model Configuration ===
# Pretrained model to use from SeisBench. Options: 'original', 'stead', 'instance', 'geofon', 'scedc'
# Set to None if you want to load a custom model from CUSTOM_MODEL_PATH.
MODEL_TYPE = 'original'
# Path to a custom fine-tuned model weights file (.pth).
# Set to None to use the pretrained model specified by MODEL_TYPE.
CUSTOM_MODEL_PATH = None  # e.g. "/path/to/your/model.pth"

# === Plotting Parameters ===
# LUNGHEZZA DELLA FINESTRA DI VISUALIZZAZIONE PER SUBPLOT (in secondi)
WLENGTH_SECONDS = 900 # 30 min
# =====================================================================
# GAMMA CONFIGURATION
# =====================================================================
    
    
# SET GaMMA PARAMETERS
# Define coordinate systems 
wgs84 = CRS.from_epsg(4326)  # Latitude/Longitude
utm33n = CRS.from_epsg(32633)  # UTM zone 33N (only for Central Italy)
transformer = Transformer.from_crs(wgs84, utm33n, always_xy=True)
    
# Gamma
config = {}
# The seismic catalog has km coordinate as outuput data
config["dims"] = ['x(km)', 'y(km)', 'z(km)']
config["use_dbscan"] = True
config["use_amplitude"] = True
config["x(km)"] = (250, 600)
config["y(km)"] = (4100, 5000)
config["z(km)"] = (0, 150)
config["vel"] = {"p": 7.0, "s": 7.0 / 1.75}  # We assume rather high velocities as we expect deeper events
config["method"] = "BGMM"
if config["method"] == "BGMM":
    config["oversample_factor"] = 4
if config["method"] == "GMM":
    config["oversample_factor"] = 1
    
# DBSCAN
config["bfgs_bounds"] = (
    (config["x(km)"][0] - 1, config["x(km)"][1] + 1),  # x
    (config["y(km)"][0] - 1, config["y(km)"][1] + 1),  # y
    (0, config["z(km)"][1] + 1),  # x
    (None, None),  # t
)
#config["dbscan_eps"] = estimate_eps(stations, config["vel"]["p"]) 
config["dbscan_eps"] = 25  # seconds
config["dbscan_min_samples"] = 3
    
## using Eikonal for 1D velocity model
zz = [0.0, 5.5, 16.0, 32.0]
vp = [5.5, 5.5,  6.7,  7.8]
vp_vs_ratio = 1.73
vs = [v / vp_vs_ratio for v in vp]
h = 1.0
vel = {"z": zz, "p": vp, "s": vs}
config["eikonal"] = {"vel": vel, "h": h, "xlim": config["x(km)"], "ylim": config["y(km)"], "zlim": config["z(km)"]}
    
# Filtering
config["min_picks_per_eq"] = 6
config["min_p_picks_per_eq"] = 4
config["min_s_picks_per_eq"] = 3
config["max_sigma11"] = 1.5 # second
config["max_sigma22"] = 1.0 # log10(m/s)
config["max_sigma12"] = 1.0 # covariance
# === PyGMT Configuration ===
# Define the path to your GMT library if it's not in the default system path.
GMT_LIBRARY_PATH = os.environ.get("GMT_LIBRARY_PATH", "")
# Path to local topography grid file or a PyGMT remote dataset (e.g., "@earth_relief_15s")
GMT_GRID_PATH = os.environ.get("GMT_GRID_PATH", "@earth_relief_15s")

# === Script 04_2 Parameters ===
analysis_log_filename = "analisi_picking.log"
# === Script 04_3 Parameters ===
# Map region [min_lon, max_lon, min_lat, max_lat]
plot_region = [12.5, 14.00, 42.00, 43.50]
# Map title
plot_map_title = "Central Italy - Seismicity"

# === Script 05 Parameters ===
# Minimum number of P picks per event for Hypoellipse filtering
h71_min_p = 4
# Minimum number of S picks per event for Hypoellipse filtering
h71_min_s = 2


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
station_file_name = "stations.csv"  # station file name (used by script 06)

# === FDSN Clients ===
def get_fdsn_clients():
    """Returns a list of FDSN clients. 
    Initialized on demand to avoid connection errors during imports."""
    clients = []
    for provider in fdsn_clients:
        try:
            clients.append(Client(provider))
        except Exception as e:
            print(f"Warning: Could not connect to {provider} FDSN service: {e}")
    return clients

# --- SETUP DIRECTORIES CONTAINING THE OUTPUTS OF THE SCRIPTS ---
root_dir = os.path.join(base_dir, case_study_name, "waveforms")  
inventory_dir = os.path.join(base_dir, case_study_name, "inventory")
waveform_base = os.path.join(root_dir, str(year))  # where script 02+ reads from
output_base = os.path.join(base_dir, case_study_name, "output")
output_picks_dir = os.path.join(output_base, f"output_picks_{P_THRESHOLD}")
plot_dir = os.path.join(output_base, "plots_annotations", f"{year}_{start_day:03d}_{end_day:03d}")
log_file_path = os.path.join(output_base, "phase_picking_log.txt")  # used by scripts 02+
# Used by script 04_1 for the output
output_dir = os.path.join(output_base, "output_catalog")
# Used by script 05 and script 06 for the filtered Hypoellipse output
h71_filtered_dir = os.path.join(output_dir, "filtered_data")

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
# Loads a custom fine-tuned PhaseNet model from a local .pth file if CUSTOM_MODEL_PATH is set,
# otherwise loads the pretrained model specified by MODEL_TYPE from SeisBench.
if CUSTOM_MODEL_PATH is not None:
    model = PhaseNet()
    import torch as _torch
    model.load_state_dict(_torch.load(CUSTOM_MODEL_PATH, map_location=device))
    model.eval()
    print(f"Custom model loaded from: {CUSTOM_MODEL_PATH}")
else:
    model = PhaseNet.from_pretrained(MODEL_TYPE)
    print(f"Pretrained model loaded: PhaseNet '{MODEL_TYPE}'")
