#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Jan 30 11:23:19 2026

@author: rossella.fonzetti
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import matplotlib.pyplot as plt
import os

# --- 1. Define Paths and Threshold ---
model="PRETRAINED_ORIGINAL"
base_dir = f"/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/{model}"
#PN_60_epochs_4096_bs_0.0001_lr_std_norm.AQ2009_transferlearning_focalloss_20250627_143520_
#PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_focalloss_
#PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_transferlearning_crossentropy_
#EP_41_PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_crossentropy_
threshold = "01-01"

input_file_name = f'location-1D_{threshold}.quality'
pdf_output_file = f'histograms_{threshold}_filtered.pdf'

full_input_path = os.path.join(base_dir, input_file_name)
full_output_path = os.path.join(base_dir, pdf_output_file)

columns_to_plot = ['N_P', 'N_S', 'GAP', 'RMS_HE', 'SEH', 'SEZ']

# --- 2. Caricamento e Filtraggio Dati ---
try:
    # Lettura del file (spazi come separatore)
    df = pd.read_csv(full_input_path, sep='\s+')

    # Applicazione dei filtri richiesti:
    # GAP > 180, RMS < 0.6, ERH (SEH) < 1.5, EHZ (SEZ) < 1.5
    df_filtered = df[
        (df['GAP'] < 180) & 
        (df['RMS_HE'] < 0.6) & 
        (df['SEH'] < 1.5) & 
        (df['SEZ'] < 1.5)
    ].copy()

    if df_filtered.empty:
        print("ATTENZIONE: Nessun dato soddisfa i criteri di filtraggio.")
    else:
        print(f"Dati totali: {len(df)} | Dati dopo il filtro: {len(df_filtered)}")

        # --- 3. Creazione del Grafico ---
        fig, axes = plt.subplots(nrows=3, ncols=2, figsize=(12, 14))
        fig.suptitle(f'Analisi Qualità Localizzazioni - {model}', 
                     fontsize=16, fontweight='bold', y=0.98)
        
        axes = axes.flatten()

        # Palette colori
        color_standard = '#3498db'  # Blu elegante per i primi 4


        for i, col_name in enumerate(columns_to_plot):
            ax = axes[i]
            
            # Gestione dati per SEH e SEZ (rimozione valori nulli/errori > 99)
            if col_name in ['SEH', 'SEZ']:
                data_to_plot = df_filtered[col_name][df_filtered[col_name] < 99]
                current_color = color_standard
                # rwidth=1.0 elimina lo spazio tra le barre
                r_width = 1.0 
                edge_c = 'white'
                bins_n = 15 # Meno bin per dare un effetto più compatto
                title_suffix = "(Errors < 1.5 km)"
            else:
                data_to_plot = df_filtered[col_name]
                current_color = color_standard
                r_width = 0.9
                edge_c = 'white'
                bins_n = 30
                title_suffix = ""

            # Plot dell'istogramma
            ax.hist(data_to_plot, bins=bins_n, color=current_color, 
                    edgecolor=edge_c, alpha=0.85, rwidth=r_width)

            # Estetica degli assi
            ax.set_title(f'Histogram {col_name} {title_suffix}', fontsize=12, fontweight='semibold')
            ax.set_xlabel('Value', fontsize=10)
            ax.set_ylabel('Frequency (Count)', fontsize=10)
            ax.grid(axis='y', linestyle='--', alpha=0.5)
            
            # Rende il grafico più pulito eliminando i bordi superiore e destro
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)

        # Ottimizzazione layout
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        
        # Salvataggio
        plt.savefig(full_output_path, dpi=300, format='pdf')
        
        print(f"\nSuccesso! Il file PDF è stato salvato in:\n{full_output_path}")

except FileNotFoundError:
    print(f"Errore: Il file {full_input_path} non è stato trovato.")
except Exception as e:
    print(f"Si è verificato un errore: {e}")