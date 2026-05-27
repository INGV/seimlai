#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration file for all scripts.
Contains environment variables, paths, and parameters shared across the pipeline.

Structure:
  1. USER CONFIGURATION — All variables the user must set, ordered by script.
  2. SYSTEM VARIABLES   — Everything derived automatically (paths, device, model).
"""

import os
from obspy import UTCDateTime
from obspy.clients.fdsn import Client
import torch
from seisbench.models import PhaseNet, EQTransformer
from pyproj import CRS, Transformer

# =====================================================================
# 1. USER CONFIGURATION (ordered by script)
# =====================================================================

# --- General / Case Study ---
case_study_name = "Amatrice_catalog"
# Set to a path (e.g. "/path/to/external/folder") to store all data and output there.
# If None, the folder [case_study_name] will be created in the current directory.
PERSONAL_FOLDER = None
# Set to True to run the download script (01).
# Set to False to skip it and use existing data if you have put yout own folder.
DOWNLOAD_DATA = True 

# --- Geographic Bounding Box (scripts 01, 04_1) ---
minlatitude = 42.25
maxlatitude = 43.12
minlongitude = 11.75
maxlongitude = 14.00

# --- Time Interval (scripts 01, 02, …) ---
starttime = UTCDateTime("2016-10-26")
endtime = UTCDateTime("2016-10-31")
year = 2016

# --- Station Parameters (script 01) ---
network = "*"                # network code
channel = "BH?,HH?,EH?"      # channel types
stations_list = "*"
# fdsn_clients = ["INGV", "IRIS"]
fdsn_clients = ["IRIS"]

# --- Model Configuration (script 02) ---
# Select the neural network architecture. Options: 'PhaseNet' or 'EQTransformer' (Case insensitive)
NEURAL_NETWORK = 'PhaseNet'

# Pretrained model to use from SeisBench. Options: 'original', 'stead', 'instance', 'geofon', 'scedc'
# Set to None if you want to load a custom model from CUSTOM_MODEL_PATH.
MODEL_TYPE = 'original'
# Path to a custom fine-tuned model weights file (.pth).
# Set to None to use the pretrained model specified by MODEL_TYPE.
CUSTOM_MODEL_PATH = None
# --- Picking Parameters (script 02) ---
BATCH_SIZE = 256 #use 2048 for HPC cluster
P_THRESHOLD = 0.1
S_THRESHOLD = 0.1

# --- Plotting Parameters (script 02) ---
# LUNGHEZZA DELLA FINESTRA DI VISUALIZZAZIONE PER SUBPLOT (in secondi)
WLENGTH_SECONDS = 900 # 30 min

# =====================================================================
# GAMMA CONFIGURATION (script 04_1)
# =====================================================================

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
config["x(km)"] = (230, 620)   # adjust to actual values
config["y(km)"] = (4650, 4800) # adjust to actual values
config["z(km)"] = (0, 60)      # 150 km is too deep for Amatrice
config["vel"] = {"p": 7.0, "s": 7.0 / 1.75}  # We assume rather high velocities as we expect deeper events
config["method"] = "BGMM"
if config["method"] == "BGMM":
    config["oversample_factor"] = 4
if config["method"] == "GMM":
    config["oversample_factor"] = 1
    
# DBSCAN
config["bfgs_bounds"] = (
    (config["x(km)"][0] - 1, config["x(km)"][1] + 1),
    (config["y(km)"][0] - 1, config["y(km)"][1] + 1),
    (0, config["z(km)"][1] + 1),
    (None, None),
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

# --- Script 04_2 Parameters ---
analysis_log_filename = "analisi_picking.log"

# --- Script 04_3 Parameters (PyGMT) ---
# Define the path to your GMT library if it's not in the default system path.
GMT_LIBRARY_PATH = os.environ.get("GMT_LIBRARY_PATH", "")
# Path to local topography grid file or a PyGMT remote dataset (e.g., "@earth_relief_15s")
GMT_GRID_PATH = os.environ.get("GMT_GRID_PATH", "@earth_relief_15s")
# Map region [min_lon, max_lon, min_lat, max_lat]
plot_region = [12.5, 14.00, 42.00, 43.50]
# Map title
plot_map_title = "Central Italy - Seismicity"

# --- Script 05 Parameters ---
# Minimum number of P picks per event for Hypoellipse filtering
h71_min_p = 4
# Minimum number of S picks per event for Hypoellipse filtering
h71_min_s = 2

# --- Script 10 Parameters ---
# Filtering criteria for hypoDD file generation
DD_MAX_GAP = 180.0
DD_MAX_RMS = 0.4
DD_MAX_ERH = 0.8
DD_MAX_ERZ = 0.8

# --- Script 11 Parameters ---
MAX_DIST_KM_CC = 3.0       # Maximum distance between event pairs for CC (km)
CC_THRESHOLD_11 = 0.7      # Minimum cross-correlation coefficient
WIN_BEFORE_CC = 0.2        # Window before pick (s)
WIN_AFTER_CC = 0.8         # Window after pick (s)
CC_MAX_LAG_11 = 0.5        # Maximum lag for cross-correlation (s)
FREQ_MIN_CC = 2.0           # Bandpass filter min frequency (Hz)
FREQ_MAX_CC = 15.0          # Bandpass filter max frequency (Hz)
CC_NETWORK = "3A"           # Network code for waveform loading in script 11

# --- Script 12 Parameters ---
# Threshold map for analysing multiple runs across different P/S thresholds
THRESHOLDS_MAP_12 = {
    "01-01": 0.1, "02-02": 0.2, "03-03": 0.3,
    "04-04": 0.4, "05-05": 0.5, "06-06": 0.6,
    "07-07": 0.7, "08-08": 0.8, "09-09": 0.9,
}


# =====================================================================
# 2. SYSTEM VARIABLES (Automatically derived — do not edit)
# =====================================================================

# --- Time Interval (Derived) ---
# Days corresponding to the interval
start_day = starttime.julday
end_day = endtime.julday

# --- Threshold String (Derived) ---
# Used to name output files of scripts 08-12.
THR = f"{int(P_THRESHOLD*10):02d}-{int(S_THRESHOLD*10):02d}"

# --- Directory Paths ---
base_dir = os.getcwd()
if PERSONAL_FOLDER:
    project_root = PERSONAL_FOLDER
else:
    project_root = os.path.join(os.getcwd(), case_study_name)

# Ensure the main directory exists
os.makedirs(project_root, exist_ok=True)

inventory_dir = os.path.join(project_root, "inventory")
download_log_path = os.path.join(project_root, "download_log.txt")  # used by script 01
station_file_name = "stations.csv"  # station file name (used by script 06)

# --- FDSN Clients ---
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
root_dir = os.path.join(project_root, "waveforms")  
inventory_dir = os.path.join(project_root, "inventory")
waveform_base = os.path.join(root_dir, str(year))  # where script 02+ reads from
output_base = os.path.join(project_root, "output")
output_picks_dir = os.path.join(output_base, f"output_picks_{P_THRESHOLD}")
#plot_dir = os.path.join(output_base, f"plots_annotations_{P_THRESHOLD}", f"{year}_{start_day:03d}_{end_day:03d}")
log_file_path = os.path.join(output_base, "phase_picking_log.txt")  # used by scripts 02+
# Used by script 04_1 for the output
output_dir = os.path.join(output_base, f"output_catalog_{P_THRESHOLD}")
# Used by script 05 and script 06 for the filtered Hypoellipse output
h71_filtered_dir = os.path.join(output_dir, "filtered_data")
# Additional path needed for some scripts
case_study_dir = project_root

# --- PHASE 2: DD directory and derived paths (scripts 08-12) ---
# The DD folder stores the location-1D.out file from Hypoellipse and all derived files
dd_dir = os.path.join(output_dir, "DD")

# Script 08: Input/Output
location_1d_out_path = os.path.join(dd_dir, "location-1D.out")
location_1d_quality_path = os.path.join(dd_dir, f"location-1D_{THR}.quality")

# Script 10: hypoDD input file generation
phs_file_path = os.path.join(h71_filtered_dir, "out_conv.phs")
stations_csv_path = os.path.join(project_root, station_file_name)
dd_output_file = os.path.join(dd_dir, f"travel_{THR}.dat")
dd_station_file = os.path.join(dd_dir, f"station_{THR}.dat")

# Script 11: Cross-correlation DD
dd_dtcc_file = os.path.join(dd_dir, "dt.cc")

# Script 12: Threshold analysis outputs
CSV_FILENAME_12 = f"seismic_catalog_with_latlon_{year}_{start_day:03d}_{end_day:03d}.csv"
output_bar_path_12 = os.path.join(output_base, "grouped_bar_charts.pdf")
output_line_path_12 = os.path.join(output_base, "line_charts_vs_THR.pdf")

# --- Device Configuration ---
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
# Loads a custom fine-tuned PhaseNet/EQTransformer model from a local .pth file if CUSTOM_MODEL_PATH is set,
# otherwise loads the pretrained model specified by MODEL_TYPE from SeisBench.

network_choice = NEURAL_NETWORK.lower()

if CUSTOM_MODEL_PATH is not None:
    if network_choice == 'eqtransformer':
        model = EQTransformer()
    else:
        model = PhaseNet()
        model.labels = "PSN"
        
    import torch as _torch
    
    # Carica il file .pth
    checkpoint = _torch.load(CUSTOM_MODEL_PATH, map_location=device)
    
    # Se il file è un checkpoint, estrae solo i pesi del modello. 
    # Altrimenti, carica il file direttamente.
    if "model_state_dict" in checkpoint:
        model.load_state_dict(checkpoint["model_state_dict"])
    else:
        model.load_state_dict(checkpoint)
        
    
    # Carica il file .pth
    checkpoint = _torch.load(CUSTOM_MODEL_PATH, map_location=device)
    
    # Se il file è un checkpoint, estrae solo i pesi del modello. 
    # Altrimenti, carica il file direttamente.
    if "model_state_dict" in checkpoint:
        model.load_state_dict(checkpoint["model_state_dict"])
    else:
        model.load_state_dict(checkpoint)
        
    print(f"Custom model loaded from: {CUSTOM_MODEL_PATH}")
else:
    if network_choice == 'eqtransformer':
        model = EQTransformer.from_pretrained(MODEL_TYPE)
        print(f"Pretrained model loaded: EQTransformer '{MODEL_TYPE}'")
    else:
        model = PhaseNet.from_pretrained(MODEL_TYPE)
        print(f"Pretrained model loaded: PhaseNet '{MODEL_TYPE}'")
model.to(device)
model.eval()
