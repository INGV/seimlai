#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov 13 10:47:52 2025

@author: rossella.fonzetti
"""
# --- 1. Importare le librerie necessarie ---
import pandas as pd  # Per leggere e analizzare il file CSV
import os          # Per gestire i percorsi delle cartelle e dei file
from config import *

# --- 2. Definizione dei percorsi (derived from config.py) ---

# Input file name built from config variables (year, start_day, end_day)
nome_file_input = f"gamma_pick_{year}_{start_day}_{end_day}.csv"

# Build full paths using output_dir from config.py
input_file_path = os.path.join(output_dir, nome_file_input)
log_file_path = os.path.join(output_dir, analysis_log_filename)

# --- 3. Stampa di controllo (per te) ---
print(f"Sto per leggere il file da:\n{input_file_path}\n")
print(f"Salverò il file di log in:\n{log_file_path}\n")

# --- 4. Blocco di analisi (con gestione errori) ---
try:
    # --- 5. Lettura del file di input ---
    # Pandas legge il file CSV dal percorso completo che abbiamo costruito
    df = pd.read_csv(input_file_path)
    print("File di input letto con successo.")

    # --- 6. Esecuzione dei calcoli ---
    print("Inizio i calcoli...")
    
    # Filtri per tipo 'p' e 's'
    is_p = df['type'] == 'p'
    is_s = df['type'] == 's'
    
    # Conteggi totali
    total_p = is_p.sum()
    total_s = is_s.sum()

    # Filtri per associazione
    # Gestiamo sia il caso in cui -1 sia intero o float (più sicuro)
    if pd.api.types.is_float_dtype(df['event_idx']):
        unassoc_condition = (df['event_idx'] == -1.0) | (df['event_idx'] == -1)
        assoc_condition = (df['event_idx'] != -1.0) & (df['event_idx'] != -1)
    else:
        unassoc_condition = df['event_idx'] == -1
        assoc_condition = df['event_idx'] != -1
    
    # Conteggi non associati (tipo E condizione)
    unassociated_p = (is_p & unassoc_condition).sum()
    unassociated_s = (is_s & unassoc_condition).sum()
    
    # Conteggi associati (tipo E condizione)
    associated_p = (is_p & assoc_condition).sum()
    associated_s = (is_s & assoc_condition).sum()
    
    print("Calcoli completati.")

    # --- 7. Scrittura del file di log ---
    # Apriamo il file di log nel percorso completo in modalità scrittura ('w')
    # 'with' garantisce che il file venga chiuso correttamente
    with open(log_file_path, 'w', encoding='utf-8') as f:
        # Scriviamo i risultati nel file, riga per riga
        f.write(f"Analisi del file: {input_file_path}\n\n")
        
        f.write("--- CONTEGGI TOTALI ---\n")
        f.write(f"Onde P totali: {total_p}\n")
        f.write(f"Onde S totali: {total_s}\n")
        
        f.write("\n--- ONDE NON ASSOCIATE (event_idx = -1) ---\n")
        f.write(f"Onde P non associate: {unassociated_p}\n")
        f.write(f"Onde S non associate: {unassociated_s}\n")
        
        f.write("\n--- ONDE ASSOCIATE (event_idx != -1) ---\n")
        f.write(f"Onde P associate: {associated_p}\n")
        f.write(f"Onde S associate: {associated_s}\n")
    
    print(f"\n--- OPERAZIONE COMPLETATA ---")
    print(f"File di log creato con successo in:\n{log_file_path}")

# --- 8. Gestione degli errori ---
except FileNotFoundError:
    print(f"\n--- ERRORE ---")
    print(f"File non trovato. Controlla che il percorso sia corretto:")
    print(f"{input_file_path}")
    
except KeyError as e:
    print(f"\n--- ERRORE ---")
    print(f"Colonna non trovata: {e}. Controlla che il file CSV contenga le colonne 'type' e 'event_idx'.")

except Exception as e:
    print(f"\n--- ERRORE IMPREVISTO ---")
    print(f"Si è verificato un errore: {e}")
