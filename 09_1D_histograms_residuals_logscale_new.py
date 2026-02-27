#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb  6 16:36:56 2026

@author: rossella.fonzetti
"""

import matplotlib.pyplot as plt
import os
import re
import numpy as np

# --- 1. Configurazione dei Percorsi ---
# Modello attivo selezionato dall'utente
#model = "PN_60_epochs_4096_bs_0.0001_lr_std_norm.AQ2009_transferlearning_focalloss_20250627_143520_"

# Altri modelli disponibili (commentati)
#model = "EP_41_PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_crossentropy_"
model = "PRETRAINED_ORIGINAL"
#model = "PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_focalloss_"
#model = "PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_transferlearning_crossentropy_"

base_dir = f"/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/{model}"
threshold = "01-01"

# Definizione file di input e output
input_file_name = f'location-1D_{threshold}.out'
pdf_output_file = f'residuals_outliers_A4_fixed_axes_{threshold}.pdf'

full_input_path = os.path.join(base_dir, input_file_name)
full_output_path = os.path.join(base_dir, pdf_output_file)

# --- 2. Criteri di Filtro (Quality Parameters) ---
FILTER_GAP = 180.0
FILTER_RMS = 0.6
FILTER_SEH = 1.5
FILTER_SEZ = 1.5

# Liste per memorizzare i residui
p_res_all = []
s_res_all = []
p_res_filtered = []
s_res_filtered = []

# Contatori per le statistiche
stats = {'total_events': 0, 'passed_filters': 0}

# --- 3. Parsing del file .out ---
try:
    if not os.path.exists(full_input_path):
        raise FileNotFoundError(f"File non trovato: {full_input_path}")

    with open(full_input_path, 'r') as f:
        content = f.read()

    # Suddivisione del file per ogni evento sismico
    event_blocks = content.split("earthquake location")
    
    for block in event_blocks[1:]:
        stats['total_events'] += 1
        lines = block.split('\n')
        gap = rms = seh = sez = None
        
        # Estrazione parametri di qualità dalle tabelle o tramite regex
        for i, line in enumerate(lines):
            if 'gap d  rms' in line and i + 1 < len(lines):
                parts = lines[i+1].split()
                if len(parts) >= 11:
                    gap = float(parts[-5])
                    rms = float(parts[-3])
            
            if 'seh  sez q sqd' in line and i + 1 < len(lines):
                parts = lines[i+1].split()
                if len(parts) >= 2:
                    seh = float(parts[0])
                    sez = float(parts[1])

        if seh is None:
            m = re.search(r"seh\s*=\s*([\d\.]+)", block)
            if m: seh = float(m.group(1))
        if sez is None:
            m = re.search(r"sez\s*=\s*([\d\.]+)", block)
            if m: sez = float(m.group(1))
        if rms is None:
            m = re.search(r"se of orig\s*=\s*([\d\.]+)", block)
            if m: rms = float(m.group(1))

        # Verifica filtri di qualità
        is_filtered = False
        if all(v is not None for v in [gap, rms, seh, sez]):
            if gap < FILTER_GAP and rms < FILTER_RMS and seh < FILTER_SEH and sez < FILTER_SEZ:
                is_filtered = True
                stats['passed_filters'] += 1

        # Estrazione dei Residui P e S
        in_travel_times = False
        for line in lines:
            if "-- travel times and delays --" in line:
                in_travel_times = True
                continue
            if in_travel_times:
                if len(line.strip()) == 0 or "---" in line: continue
                parts = line.split()
                if len(parts) < 5: continue
                
                res_val = None
                phase_type = None
                try:
                    if 'EP' in parts or 'P' in parts:
                        phase_type = 'P'
                        idx = parts.index('EP') if 'EP' in parts else parts.index('P')
                        res_val = float(parts[idx+3])
                    elif 'ES' in parts or 'S' in parts:
                        phase_type = 'S'
                        idx = parts.index('ES') if 'ES' in parts else parts.index('S')
                        res_val = float(parts[idx+3])
                    
                    if res_val is not None:
                        if phase_type == 'P': p_res_all.append(res_val)
                        else: s_res_all.append(res_val)
                        if is_filtered:
                            if phase_type == 'P': p_res_filtered.append(res_val)
                            else: s_res_filtered.append(res_val)
                except: continue

    # --- 4. Plotting (Formato A4 2x2 Layout) ---
    A4_WIDTH = 11.69
    A4_HEIGHT = 8.27
    fig, axes = plt.subplots(2, 2, figsize=(A4_WIDTH, A4_HEIGHT))
    
    fig.suptitle(f'Residuals Analysis (Log Scale) - File: {input_file_name}\nFilters: GAP<{FILTER_GAP}, RMS<{FILTER_RMS}, SEH/SEZ<{FILTER_SEH}', 
                 fontsize=14, fontweight='bold', y=0.97)

    plot_configs = [
        {'data': p_res_all,      'ax': axes[0, 0], 'title': 'P Residuals - All Events', 'color': '#4682B4'},
        {'data': s_res_all,      'ax': axes[0, 1], 'title': 'S Residuals - All Events', 'color': '#5F9EA0'},
        {'data': p_res_filtered, 'ax': axes[1, 0], 'title': 'P Residuals - Filtered',   'color': '#1F497D'},
        {'data': s_res_filtered, 'ax': axes[1, 1], 'title': 'S Residuals - Filtered',   'color': '#3E5B76'}
    ]

    for i, config in enumerate(plot_configs):
        ax = config['ax']
        data = config['data']
        
        if data:
            data_np = np.array(data)
            mu, std = np.mean(data_np), np.std(data_np)
            d_min, d_max = np.min(data_np), np.max(data_np)
            
            # Istogramma logaritmico
            ax.hist(data, bins=60, color=config['color'], edgecolor='white', 
                    linewidth=0.3, alpha=0.85, log=True)
            
            ax.axvline(0, color='red', linestyle='--', linewidth=1, alpha=0.5)
            
            # Box statistiche
            stats_text = (f"N: {len(data)}\n"
                          f"Mean: {mu:.3f}\n"
                          f"StdDev: {std:.3f}\n"
                          f"Min: {d_min:.2f}\n"
                          f"Max: {d_max:.2f}")
            
            props = dict(boxstyle='round', facecolor='white', alpha=0.7)
            ax.text(0.05, 0.95, stats_text, transform=ax.transAxes, fontsize=8,
                    verticalalignment='top', bbox=props, family='monospace')
        
        # --- Modifica Limiti: Solo per gli ultimi due grafici (Filtered) ---
        if i >= 2:
            ax.set_xlim([-8, 8])
            ax.set_ylim([1, 100000]) # 10^5
        
        ax.set_title(config['title'], fontsize=11, fontweight='semibold')
        ax.set_xlabel('Residual (s)', fontsize=10)
        ax.set_ylabel('Frequency (Log Scale)', fontsize=10)
        ax.tick_params(labelsize=9)
        ax.grid(True, which="both", ls="-", alpha=0.1)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    plt.tight_layout(rect=[0.05, 0.03, 0.95, 0.95])
    plt.savefig(full_output_path, dpi=300, bbox_inches='tight')
    
    print(f"\nElaborazione completata.")
    print(f"Eventi totali: {stats['total_events']}")
    print(f"Eventi passati: {stats['passed_filters']}")
    print(f"Output: {full_output_path}")

except Exception as e:
    print(f"Errore: {e}")