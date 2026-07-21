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
from concurrent.futures import ThreadPoolExecutor
import threading
import sys

get_fdsn_clients = None
log_file = None
io_lock = threading.Lock()
station_metadata = []


def _apply_context(ctx):
    globals().update(ctx.legacy_globals(include_fdsn=True))

def log(message):
    """Writes a message both to the screen and to a file in a thread-safe manner"""
    with io_lock:
        print(message)
        log_file.write(message + "\n")

# === Helper function for clients ===
def try_with_clients(method_name, *args, **kwargs):
    clients = get_fdsn_clients()
    if not clients:
        raise RuntimeError(f"No FDSN clients available to call {method_name}.")
    
    for client in clients:
        try:
            method = getattr(client, method_name)
            return method(*args, **kwargs)
        except Exception as e:
            continue
    raise RuntimeError(f"All clients failed for {method_name}.")

def get_combined_stations(*args, **kwargs):
    """
    Queries all FDSN clients and combines their inventories.
    Returns a single ObsPy Inventory object.
    """
    clients = get_fdsn_clients()
    if not clients:
        raise RuntimeError("No FDSN clients available to get stations.")
    
    combined_inv = None
    for client in clients:
        try:
            log(f"  [Info] Requesting stations from client...")
            inv = client.get_stations(*args, **kwargs)
            if combined_inv is None:
                combined_inv = inv
            else:
                combined_inv += inv
            log(f"  [Info] Successfully added stations from client.")
        except Exception as e:
            log(f"  [Info] A client failed to get_stations: {e}")
            
    if combined_inv is None:
        raise RuntimeError("All clients failed to get_stations.")
    
    return combined_inv

# === Worker Function for Parallel Downloads ===
def process_single_channel(net_code, sta_code, comp, t0, t1, year, day_of_year):
    """
    This function is performed in parallel by multiple workers.
    Download a single channel for a single day.
    """
    try:
        st = try_with_clients("get_waveforms", network=net_code, station=sta_code, 
                              location="*", channel=comp, starttime=t0, endtime=t1)
        folder = os.path.join(root_dir, year, net_code, sta_code, f"{comp}.D")
        os.makedirs(folder, exist_ok=True)

        filename = f"{net_code}.{sta_code}..{comp}.D.{year}.{day_of_year}"
        filepath = os.path.join(folder, filename)

        if not os.path.exists(filepath):
            st.write(filepath, format="MSEED")
            log(f"Saved: {filepath}")
        else:
            log(f"Skipped (already exists): {filepath}")

    except Exception as e:
        err_msg = str(e)
        if "No data" in err_msg or "404" in err_msg:
             log(f"  [Info] Missing data for {net_code}.{sta_code}.{comp}")
             pass
        else:
            log(f"  [!] ERROR downloading {net_code}.{sta_code}.{comp}: {err_msg}")


def run(ctx):
    global io_lock, log_file, station_metadata
    _apply_context(ctx)

    if PERSONAL_FOLDER is not None and not DOWNLOAD_DATA:
        print(f"\n[SKIP] PERSONAL_FOLDER is set but DOWNLOAD_DATA is False in user_configuration/config.yaml.")
        print("      Skipping download (Step 01). Set download_data = true to download to personal_folder.")
        return

    # === Create directories ===
    os.makedirs(root_dir, exist_ok=True)
    os.makedirs(inventory_dir, exist_ok=True)

    station_metadata = []

    # === Open log file & Lock ===
    log_file = open(download_log_path, "w")
    # Il lock serve a evitare che due processi scrivano nel file nello stesso istante
    io_lock = threading.Lock()

    # === MAIN EXECUTION ===
    overall_start = datetime.now()
    log(f"=== Download started at {overall_start.strftime('%Y-%m-%d %H:%M:%S')} ===")

    current_time = starttime
    one_day_seconds = 24 * 60 * 60

    while current_time <= endtime:
        t0 = current_time
        t1 = current_time + one_day_seconds

        log(f"\n>> Downloading day {t0.date}")

        try:
            inventory = get_combined_stations(starttime=t0, endtime=t1,
                                             minlatitude=minlatitude, maxlatitude=maxlatitude,
                                             minlongitude=minlongitude, maxlongitude=maxlongitude,
                                             level="response", network=network, channel=channel,
                                             station=stations_list)
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

                        try:
                            if chan.response and not sensor:
                                sensor = chan.sensor.description
                                gain = chan.response.instrument_sensitivity.value
                        except:
                            pass
                    
                        task = (net_code, sta_code, comp, t0, t1, year, day_of_year)
                        if task not in download_tasks:
                            download_tasks.append(task)

                    # === Save StationXML inventory (Veloce, sequenziale) ===
                    try:
                        single_inv = inventory.select(network=net_code, station=sta_code)
                        xml_filename = f"{net_code}.{sta_code}.xml"
                        xml_path = os.path.join(inventory_dir, xml_filename)
                        single_inv.write(xml_path, format="STATIONXML")
                    except Exception as e:
                        log(f"  [!] Error saving StationXML for {net_code}.{sta_code}: {e}")

                    # === Save station metadata to list ===
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

            if download_tasks:
                log(f"   Starting parallel download of {len(download_tasks)} channels...")
            
                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = [executor.submit(process_single_channel, *task) for task in download_tasks]
                

                    for future in futures:
                        future.result()

        except Exception as e:
            log(f"[!] Error fetching stations cycle: {e}")

        current_time += one_day_seconds

    print(base_dir)
    # === Save station metadata to CSV ===
    csv_path = stations_csv_path
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
            plot_path = os.path.join(archive_dir, f"waveform_plot_{sta}.pdf")
            plt.savefig(plot_path, format='pdf', dpi=300)
            log(f"Plot saved to: {plot_path}")
        else:
            log("Found station folder but could not read traces.")
    else:
        log("No complete 3-component station found for plotting.")

    overall_end = datetime.now()
    log(f"=== Download finished at {overall_end.strftime('%Y-%m-%d %H:%M:%S')} ===")
    log(f"Total duration: {str(overall_end - overall_start)}")
    log_file.close()


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_download = run


if __name__ == "__main__":
    main()
