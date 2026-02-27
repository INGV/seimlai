#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Dec  4 17:09:33 2025
Updated on Fri Dec  5 2025 - Parallel Download Version

@author: rossella.fonzetti
"""

# The parameters to be specified will be:
# 1. Directory of the experiment;
# 2. Stations data (e.g., channels, network ....);
# 3. Minimum and maximum latitude and longitude to define the extraction rectangle; 
# 4. Time interval.

# Upload libraries
from obspy import UTCDateTime, Stream, read
from obspy.clients.fdsn import Client
import os
import csv
import glob
import random
import matplotlib.pyplot as plt
from datetime import timedelta, datetime
# Nuove librerie per il parallelismo
from concurrent.futures import ThreadPoolExecutor
import threading

# === config parameters ===
case_study_name = "Amatrice_catalog"
base_dir = os.path.join(os.getcwd(), case_study_name)
root_dir = os.path.join(base_dir, "waveforms")
inventory_dir = os.path.join(base_dir, "inventory")
log_file_path = os.path.join(base_dir, "download_log.txt")

os.makedirs(root_dir, exist_ok=True)
os.makedirs(inventory_dir, exist_ok=True)

network = "YR"  # all the network
channel = "BH?,HH?,EH?"     # channel type
# Lista esatta delle stazioni YR da scaricare
stations_list = "ED01,ED02,ED03,ED04,ED05,ED06,ED07,ED08,ED09,ED10,ED11,ED12,ED14,ED15,ED16,ED17,ED18,ED19,ED20,ED21,ED22,ED23,ED24,ED25"
minlatitude = 42.25
maxlatitude = 43.12
minlongitude = 11.75
maxlongitude = 14.00

# Time interval
starttime = UTCDateTime("2016-11-01")
endtime = UTCDateTime("2016-11-10")

# === define client ===
#fdsn_clients = [Client("INGV"), Client("IRIS")]
fdsn_clients = [Client("IRIS")]

station_metadata = []

# === Open log file & Lock ===
log_file = open(log_file_path, "w")
# Il lock serve a evitare che due processi scrivano nel file nello stesso istante
io_lock = threading.Lock()

def log(message):
    """Scrive un messaggio sia a video che su file in modo thread-safe"""
    with io_lock:
        print(message)
        log_file.write(message + "\n")

# === Helper function for clients ===
def try_with_clients(method_name, *args, **kwargs):
    for client in fdsn_clients:
        try:
            method = getattr(client, method_name)
            return method(*args, **kwargs)
        except Exception as e:
            pass
    raise RuntimeError(f"All clients failed for {method_name}.")

# === Funzione Worker per il download parallelo ===
def process_single_channel(net_code, sta_code, comp, t0, t1, year, day_of_year):
    """
    Questa funzione viene eseguita in parallelo da più worker.
    Scarica un singolo canale per un singolo giorno.
    """
    try:
        # Tentativo di download
        st = try_with_clients("get_waveforms", network=net_code, station=sta_code, 
                              location="*", channel=comp, starttime=t0, endtime=t1)

        # Costruzione percorsi
        folder = os.path.join(root_dir, year, net_code, sta_code, f"{comp}.D")
        
        # Creazione cartella (os.makedirs è thread-safe nelle versioni recenti di Python, ma ok)
        os.makedirs(folder, exist_ok=True)

        filename = f"{net_code}.{sta_code}..{comp}.D.{year}.{day_of_year}"
        filepath = os.path.join(folder, filename)

        # Controllo esistenza file
        if not os.path.exists(filepath):
            st.write(filepath, format="MSEED")
            log(f"Saved: {filepath}")
        else:
            log(f"Skipped (already exists): {filepath}")

    except Exception as e:
        err_msg = str(e)
        # === GESTIONE ERRORI INTELLIGENTE ===
        # Se l'errore è "No data" o "404", è normale per le stazioni temporanee.
        # Lo logghiamo solo se vogliamo (qui ho messo pass per pulizia, o log info).
        if "No data" in err_msg or "404" in err_msg:
             # Decommenta la riga sotto se vuoi vedere i messaggi "Missing data"
             log(f"  [Info] Missing data for {net_code}.{sta_code}.{comp}")
             pass
        else:
            # Se è un errore vero (Timeout, errore scrittura, ecc), lo stampiamo!
            log(f"  [!] ERROR downloading {net_code}.{sta_code}.{comp}: {err_msg}")


# === MAIN EXECUTION ===
overall_start = datetime.now()
log(f"=== Download started at {overall_start.strftime('%Y-%m-%d %H:%M:%S')} ===")

current_time = starttime
one_day_seconds = 24 * 60 * 60

while current_time < endtime:
    t0 = current_time
    t1 = current_time + one_day_seconds
    if t1 > endtime:
        t1 = endtime

    log(f"\n>> Downloading from {t0.date} to {t1.date}")

    try:
        # 1. Scarichiamo l'inventario (Veloce, lo lasciamo sequenziale)
        inventory = try_with_clients("get_stations", starttime=t0, endtime=t1,
                                        minlatitude=minlatitude, maxlatitude=maxlatitude,
                                        minlongitude=minlongitude, maxlongitude=maxlongitude,
                                        level="channel", network=network, channel=channel,
                                        station=stations_list)

        # Lista dei "lavori" da fare in parallelo
        download_tasks = []

        for net in inventory:
            for sta in net:
                net_code = net.code
                sta_code = sta.code
                year = str(t0.year)
                day_of_year = t0.strftime('%j')
                
                sensor = ""
                gain = ""
                components_found = []

                for chan in sta:
                    comp = chan.code
                    components_found.append(comp)

                    # Recupero metadati sensore (per il CSV dopo)
                    try:
                        if chan.response and not sensor:
                            sensor = chan.sensor.description
                            gain = chan.response.instrument_sensitivity.value
                    except:
                        pass
                    
                    # Invece di scaricare qui, aggiungiamo il compito alla lista
                    # Parametri: (net, sta, comp, t0, t1, year, day_of_year)
                    download_tasks.append((net_code, sta_code, comp, t0, t1, year, day_of_year))

                # === Save StationXML inventory (Veloce, sequenziale) ===
                try:
                    single_inv = inventory.select(network=net_code, station=sta_code)
                    xml_filename = f"{net_code}.{sta_code}.xml"
                    xml_path = os.path.join(inventory_dir, xml_filename)
                    # Sovrascriviamo l'XML
                    single_inv.write(xml_path, format="STATIONXML")
                except Exception as e:
                    log(f"  [!] Error saving StationXML for {net_code}.{sta_code}: {e}")

                # === Save station metadata to list ===
                # Controlliamo se abbiamo già salvato questa stazione
                already_present = any(d['network'] == net_code and d['station'] == sta_code for d in station_metadata)
                
                if not already_present:
                    row = {
                        "network": net_code,
                        "station": sta_code,
                        "latitude": sta.latitude,
                        "longitude": sta.longitude,
                        "elevation": sta.elevation,
                        "start_date": str(sta.start_date) if sta.start_date else "",
                        "end_date": str(sta.end_date) if sta.end_date else "",
                        "components": ",".join(sorted(set(components_found))),
                        "sensor_description": sensor,
                        "instrument_gain": gain
                    }
                    station_metadata.append(row)

        # 2. ESECUZIONE PARALLELA DEI DOWNLOAD
        # max_workers=4 è ideale per un laptop standard senza sovraccaricare il server
        if download_tasks:
            log(f"   Starting parallel download of {len(download_tasks)} channels...")
            
            with ThreadPoolExecutor(max_workers=4) as executor:
                # Lanciamo tutti i task
                futures = [executor.submit(process_single_channel, *task) for task in download_tasks]
                
                # Attendiamo che finiscano tutti prima di passare al giorno successivo
                # (necessario per mantenere l'ordine cronologico nel log generale)
                for future in futures:
                    future.result() # Questo serve anche a catturare eccezioni non gestite

    except Exception as e:
        log(f"[!] Error fetching stations cycle: {e}")

    # Incrementiamo di un giorno
    current_time += one_day_seconds


# === Save station metadata to CSV ===
csv_path = os.path.join(base_dir, "stations.csv")
if station_metadata:
    fieldnames = list(station_metadata[0].keys())
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in station_metadata:
            writer.writerow(row)
    log(f"\n Station metadata saved to: {csv_path}")
else:
    log("\n No station metadata collected.")


# === Plot 3 components from a random station ===
# (Questa parte rimane identica e sequenziale per il debug visivo finale)
log("\n>> Looking for a station to plot...")
candidates = []
for year_path in os.listdir(root_dir):
    yp = os.path.join(root_dir, year_path)
    if not os.path.isdir(yp): continue
    for net in os.listdir(yp):
        np = os.path.join(yp, net)
        if not os.path.isdir(np): continue
        for sta in os.listdir(np):
            sp = os.path.join(np, sta)
            if not os.path.isdir(sp): continue
            channels = os.listdir(sp)
            if all(any(c.startswith(prefix) for c in channels) for prefix in ["HHZ", "HHN", "HHE"]):
                 candidates.append((yp, net, sta))
            elif all(any(c.startswith(prefix) for c in channels) for prefix in ["BHZ", "BHN", "BHE"]):
                 candidates.append((yp, net, sta))

if candidates:
    yp, net, sta = random.choice(candidates)
    log(f">> Plotting station: {sta} ({net})")
    stream = Stream()
    prefixes = ["HH", "BH", "EH"]
    chosen_prefix = "HH"
    station_dir = os.path.join(yp, net, sta)
    if os.path.exists(station_dir):
        existing_dirs = os.listdir(station_dir)
        for p in prefixes:
            if any(d.startswith(p) for d in existing_dirs):
                chosen_prefix = p
                break
    components = ["Z", "N", "E"]
    colors = ["red", "blue", "green"]
    found_data = False
    for comp_code, color in zip(components, colors):
        full_channel = f"{chosen_prefix}{comp_code}"
        folder = os.path.join(yp, net, sta, f"{full_channel}.D")
        if os.path.exists(folder):
            files = sorted(glob.glob(os.path.join(folder, f"*")))
            if files:
                try:
                    tr = read(files[0])[0]
                    stream += tr
                    found_data = True
                except: pass

    if found_data:
        stream.merge(method=1)
        stream.detrend("linear")
        plt.figure(figsize=(12, 6))
        for tr, color in zip(stream, colors):
            plt.plot(tr.times(), tr.data, label=tr.stats.channel, color=color, alpha=0.7)
        plt.title(f"Waveforms - Station {sta}")
        plt.xlabel("Time (s)")
        plt.ylabel("Counts")
        plt.legend()
        plt.grid()
        plt.tight_layout()
        plot_path = os.path.join(base_dir, f"waveform_plot_{sta}.pdf")
        plt.savefig(plot_path, format='pdf', dpi=300)
        log(f"Plot saved to: {plot_path}")
        # plt.show() # Decommenta se sei in Spyder/Jupyter interattivo
    else:
        log("Found station folder but could not read traces.")
else:
    log("No complete 3-component station found for plotting.")

overall_end = datetime.now()
log(f"=== Download finished at {overall_end.strftime('%Y-%m-%d %H:%M:%S')} ===")
log(f"Total duration: {str(overall_end - overall_start)}")
log_file.close()