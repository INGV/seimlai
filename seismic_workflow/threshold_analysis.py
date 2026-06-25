import pandas as pd
import matplotlib.pyplot as plt
import os
import numpy as np
import re

BASE_DIR = None

# Mappatura cartelle -> Valore Threshold per i grafici
THRESHOLDS_MAP = None

CSV_FILENAME = None
DPI = 300
output_bar_path = None
output_line_path = None


def _apply_context(ctx):
    globals().update(ctx.legacy_globals())
    globals().update({
        "BASE_DIR": output_base,
        "THRESHOLDS_MAP": THRESHOLDS_MAP_12,
        "CSV_FILENAME": CSV_FILENAME_12,
        "output_bar_path": output_bar_path_12,
        "output_line_path": output_line_path_12,
    })


# --- 2. FUNZIONE DI PARSING (LOG + CSV) ---
def parse_folder_data(folder_suffix, thr_value):
    """
    Legge il log per le statistiche delle onde e conta gli eventi dal file CSV.
    """
    folder_name = f"output_catalog_{folder_suffix}"
    folder_path = os.path.join(BASE_DIR, folder_name)
    log_path = os.path.join(folder_path, 'analisi_picking.log')
    csv_path = os.path.join(folder_path, CSV_FILENAME)
    
    data = {'THR': thr_value}

    # -- Parte A: Estrazione dati dal LOG --
    if os.path.exists(log_path):
        with open(log_path, 'r') as f:
            content = f.read()
            try:
                data['P_TOT'] = int(re.search(r"Onde P totali:\s+(\d+)", content).group(1))
                data['S_TOT'] = int(re.search(r"Onde S totali:\s+(\d+)", content).group(1))
                data['P_NO_GAMMA'] = int(re.search(r"Onde P non associate:\s+(\d+)", content).group(1))
                data['S_NO_GAMMA'] = int(re.search(r"Onde S non associate:\s+(\d+)", content).group(1))
                data['P_GAMMA'] = int(re.search(r"Onde P associate:\s+(\d+)", content).group(1))
                data['S_GAMMA'] = int(re.search(r"Onde S associate:\s+(\d+)", content).group(1))
            except (AttributeError, ValueError):
                print(f"❌ Errore parsing log in: {folder_name}")
                return None
    else:
        print(f"⚠️ Log non trovato in: {folder_name}")
        return None

    # -- Parte B: Conteggio Eventi dal CSV --
    if os.path.exists(csv_path):
        try:
            # Leggiamo solo la colonna index per velocità o contiamo semplicemente le righe
            temp_df = pd.read_csv(csv_path)
            data['N_EVE'] = len(temp_df)
        except Exception as e:
            print(f"❌ Errore lettura CSV in {folder_name}: {e}")
            data['N_EVE'] = 0
    else:
        print(f"⚠️ CSV non trovato in: {folder_name}")
        data['N_EVE'] = 0
            
    return data

def run(ctx):
    _apply_context(ctx)

    # --- 3. ELABORAZIONE DATI ---
    print("Inizio elaborazione cartelle...")
    results = []
    for folder_suffix, thr_value in THRESHOLDS_MAP.items():
        row = parse_folder_data(folder_suffix, thr_value)
        if row:
            results.append(row)

    df = pd.DataFrame(results)

    if df.empty:
        print("\n⚠️  Nessun dato trovato!")
        print("    Questo script confronta i risultati di più run con threshold diversi.")
        print("    Per ogni threshold (es. 01-01, 02-02, ...) deve esistere la cartella:")
        print(f"      {BASE_DIR}/output_catalog_XX-XX/")
        print("    contenente il file 'analisi_picking.log' (generato dal comando gamma-analysis).")
        print("\n    Se hai eseguito la pipeline una sola volta, questo script non ha dati da confrontare.")
        return

    df = df.sort_values('THR')

    # --- 4. FIGURA 1: ISTOGRAMMI RAGGRUPPATI ---
    print(f"Salvataggio istogrammi: {output_bar_path}")
    x = np.arange(len(df['THR']))
    bar_width = 0.25
    colors = ['royalblue', 'red', 'orange']

    fig1, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 8))

    # Grafico P
    ax1.bar(x - bar_width, df['P_TOT'], width=bar_width, label='P TOT', color=colors[0])
    ax1.bar(x, df['P_NO_GAMMA'], width=bar_width, label='P NO ASSOCIATION', color=colors[1])
    ax1.bar(x + bar_width, df['P_GAMMA'], width=bar_width, label='P ASSOCIATION', color=colors[2])
    ax1.set_title('P-phase vs THR', fontsize=14, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(df['THR'])
    ax1.legend(loc='upper center', bbox_to_anchor=(0.5, 1.15), ncol=3, frameon=False)
    ax1.grid(axis='y', linestyle='--', alpha=0.7)

    # Grafico S
    ax2.bar(x - bar_width, df['S_TOT'], width=bar_width, label='S TOT', color=colors[0])
    ax2.bar(x, df['S_NO_GAMMA'], width=bar_width, label='S NO ASSOCIATION', color=colors[1])
    ax2.bar(x + bar_width, df['S_GAMMA'], width=bar_width, label='S ASSOCIATION', color=colors[2])
    ax2.set_title('S-phase vs THR', fontsize=14, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(df['THR'])
    ax2.legend(loc='upper center', bbox_to_anchor=(0.5, 1.15), ncol=3, frameon=False)
    ax2.grid(axis='y', linestyle='--', alpha=0.7)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(output_bar_path, format='pdf', dpi=DPI)
    plt.close()

    # --- 5. FIGURA 2: GRAFICI A LINEE ---
    print(f"Salvataggio grafici a linee: {output_line_path}")
    fig2, axes2 = plt.subplots(3, 2, figsize=(16, 18))
    axes2 = axes2.flatten()

    # Grafico 1 e 2: Associazioni
    axes2[0].plot(df['THR'], df['P_NO_GAMMA'], marker='o', label='P_NO_GAMMA')
    axes2[0].plot(df['THR'], df['P_GAMMA'], marker='s', label='P_GAMMA')
    axes2[0].set_title('P_NO_GAMMA and P_GAMMA vs THR')

    axes2[1].plot(df['THR'], df['S_NO_GAMMA'], marker='o', label='S_NO_GAMMA')
    axes2[1].plot(df['THR'], df['S_GAMMA'], marker='s', label='S_GAMMA')
    axes2[1].set_title('S_NO_GAMMA and S_GAMMA vs THR')

    # Grafici singoli: P_TOT, S_TOT, N_EVE (da CSV)
    cols_single = ['P_TOT', 'S_TOT', 'N_EVE']
    for i, col in enumerate(cols_single):
        ax = axes2[i + 2]
        ax.plot(df['THR'], df[col], marker='o', color='tab:blue', label=col)
        ax.set_title(f'Line Chart of {col} vs THR')

    for ax in axes2[:5]:
        ax.set_xlabel('THR')
        ax.set_ylabel('Value')
        ax.grid(True)
        ax.legend()
        ax.ticklabel_format(style='sci', axis='y', scilimits=(0,3))

    axes2[-1].axis('off')
    plt.tight_layout()
    plt.savefig(output_line_path, format='pdf', dpi=DPI)
    plt.close()

    print(f"\n✅ Operazione completata! N_EVE calcolato dai file CSV.")


def main():
    from seismic_workflow.context import build_context

    run(build_context("config.yaml"))


run_threshold_analysis = run


if __name__ == "__main__":
    main()
