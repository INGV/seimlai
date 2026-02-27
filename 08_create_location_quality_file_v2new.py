#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create 'location-1D.quality' from Hypoellipse 'location-1D.out'.

Output columns (order):
IPOSTRINGA LAT LON DEPTH N_P N_S RMS_HE RMS_W RMS_UW SEH SEZ GAP

Nota: N_P e N_S escludono i pick con peso = 3 (subito dopo EP/ES).
"""
import sys, re, math
from pathlib import Path

def parse_summary_line(line):
    """Support both origin formats and variable spacing in tail columns."""
    # Format A: YYYYMMDD HH MM SS.SS ...
    # CORREZIONE: (\d{2}) -> (\d{1,3}) per gestire lat/lon a singola cifra (es. 9 gradi)
    m = re.match(
        r"\s*(\d{8}).*?(\d{1,2})\s+(\d{1,2})\s+([\d.]+)\s+"
        r"(\d{1,3})([ns])\s*([\d.]+)\s+"   
        r"(\d{1,3})([ew])\s*([\d.]+)\s+"
        r"([\-]?\d+(?:\.\d+)?)\s+(.*)$",
        line, flags=re.IGNORECASE
    )
    HH = MM = SSf = None
    if m:
        date, HHs, MMs, SSs, lat_deg, lat_hem, lat_min, lon_deg, lon_hem, lon_min, depth, tail = m.groups()
        HH, MM, SSf = int(HHs), int(MMs), float(SSs)
    else:
        # Format B: YYYYMMDD <optional junk, like '*'> HHMM SS.SS ...
        # CORREZIONE: (\d{2}) -> (\d{1,3}) per gestire lat/lon a singola cifra
        m = re.match(
            r"\s*(\d{8}).*?(\d{3,4})\s+([\d.]+)\s+"
            r"(\d{1,3})([ns])\s*([\d.]+)\s+"
            r"(\d{1,3})([ew])\s*([\d.]+)\s+"
            r"([\-]?\d+(?:\.\d+)?)\s+(.*)$",
            line, flags=re.IGNORECASE
        )
        if not m:
            return None
        date, HHMMs, SSs, lat_deg, lat_hem, lat_min, lon_deg, lon_hem, lon_min, depth, tail = m.groups()
        HHMM = int(HHMMs)
        HH, MM = HHMM // 100, HHMM % 100
        SSf = float(SSs)

    # ---------------------------------------------------------
    # TAIL PARSING ROBUSTO (Lettura a ritroso)
    # ---------------------------------------------------------
    tokens = tail.split()
    if len(tokens) < 3:
        return None
        
    try:
        # Il terzultimo token è sempre l'RMS o (D + RMS fusi)
        rms_str = tokens[-3]
        
        # Nel fortunato caso in cui manchi il decimale (anomalia estrema), proviamo a convertire lo stesso
        rms_val = float(rms_str)
        
        # Se l'RMS è maggiore o uguale a 10, è fuso con la distanza 'd' (es. "113.5414")
        if rms_val >= 10.0 and "." in rms_str:
            rms_he = float("0." + rms_str.split(".")[1])
            # Poiché 'd' si è fuso, il token precedente (-4) è il GAP
            gap = int(tokens[-4])
        else:
            rms_he = rms_val
            # Non ci sono fusioni, quindi il token precedente (-4) è 'd', 
            # e quello ancora prima (-5) è il GAP
            gap = int(tokens[-5])
            
    except (ValueError, IndexError):
        return None

    return {
        "date": date, "HH": HH, "MM": MM, "SSf": SSf,
        "lat_deg": lat_deg, "lat_hem": lat_hem, "lat_min": lat_min,
        "lon_deg": lon_deg, "lon_hem": lon_hem, "lon_min": lon_min,
        "depth": float(depth), "gap": gap, "rms_he": rms_he,
    }

def parse_events(lines):
    events = []
    N = len(lines); i = 0
    while i < N:
        if re.search(r"\bdate\s+origin\s+lat\s+long\s+depth\b", lines[i]):
            # summary line (next non-empty)
            j = i + 1
            while j < N and lines[j].strip() == "":
                j += 1
            if j >= N: break
            
            info = parse_summary_line(lines[j])
            
            if not info:
                print(f"ATTENZIONE: Evento saltato. Indice riga: {j}. Linea di riepilogo fallita: '{lines[j].strip()}'", file=sys.stderr)
                i = j + 1
                continue

            # IPOSTRINGA and coordinates
            ipostringa = f'{info["date"]}_{info["HH"]:02d}{info["MM"]:02d}{int(info["SSf"]):02d}{(info["SSf"]-int(info["SSf"])):.2f}'.replace("0.", ".")
            lat = int(info["lat_deg"]) + float(info["lat_min"]) / 60.0
            if info["lat_hem"].lower() == "s": lat = -lat
            lon = int(info["lon_deg"]) + float(info["lon_min"]) / 60.0
            if info["lon_hem"].lower() == "w": lon = -lon

            depth = info["depth"]; gap = info["gap"]; rms_he = info["rms_he"]

            # SEH/SEZ
            seh_val = math.nan; sez_val = math.nan
            for t in range(j+1, min(j+8, N-1)):
                line2 = lines[t]
                m1 = re.search(r"seh\s*=\s*([\-0-9.]+).*sez\s*=\s*([\-0-9.]+)", line2, flags=re.IGNORECASE)
                if m1:
                    seh_val = float(m1.group(1)); sez_val = float(m1.group(2)); break
                if re.search(r"^\s*seh\s+sez\b", line2, flags=re.IGNORECASE) and (t+1) < N:
                    nums = re.findall(r"[-+]?\d+\.\d+|[-+]?\d+", lines[t+1])
                    if len(nums) >= 2:
                        seh_val = float(nums[0]); sez_val = float(nums[1]); break

            # Travel times block
            k = j + 1
            while k < N and "-- travel times and delays --" not in lines[k]:
                if re.search(r"\bdate\s+origin\s+lat\s+long\s+depth\b", lines[k]):
                    k = None; break
                k += 1

            resid_vals = []; weights = []; nP = nS = 0
            if k is not None and k < N:
                k += 1
                while k < N:
                    sline = lines[k]
                    if sline.strip() == "": break
                    if "earthquake location" in sline and re.search(r"\d{2}/\d{2}/\d{2}", sline): break

                    # Conta EP/ES (includendo tutti i pesi, anche il 3)
                    if " EP " in sline or sline.strip().startswith("EP ") or " ES " in sline or sline.strip().startswith("ES "):
                        mpha = re.search(r"\b(EP|ES)\b", sline)
                        if mpha:
                            pha = mpha.group(1)
                        else:
                            # fallback
                            pha = "EP" if "EP" in sline else "ES"

                        # Incrementa sempre i contatori
                        if pha == "EP": nP += 1
                        else: nS += 1

                        # Residui e std-er per RMS
                        mres = list(re.finditer(r"\s([+-]?\d+\.\d+)\s", " "+sline+" "))
                        resid_val = float(mres[-1].group(1)) if mres else None
                        stder_val = None
                        if mres:
                            end = mres[-1].start(1)
                            left = sline[:end]
                            mstd = list(re.finditer(r"([+-]?\d+\.\d+|-----)", left))
                            if mstd:
                                cand = mstd[-1].group(1)
                                if cand != "-----":
                                    stder_val = float(cand)
                        if resid_val is not None:
                            weights.append(1.0/(stder_val**2) if (stder_val and stder_val>0) else 1.0)
                            resid_vals.append(resid_val)

                    k += 1
                i = k if k is not None else j+1
            else:
                i = j+1

            rms_uw = math.sqrt(sum(x*x for x in resid_vals)/len(resid_vals)) if resid_vals else float("nan")
            rms_w  = math.sqrt(sum(w*(x**2) for x,w in zip(resid_vals, weights))/sum(weights)) if resid_vals else float("nan")

            events.append({
                "IPOSTRINGA": ipostringa, "LAT": lat, "LON": lon, "DEPTH": depth,
                "N_P": nP, "N_S": nS,
                "RMS_HE": rms_he, "RMS_W": rms_w, "RMS_UW": rms_uw,
                "SEH": seh_val, "SEZ": sez_val, "GAP": gap
            })
        else:
            i += 1
    return events

def main(in_file, out_file):
    try:
        lines = [ln.rstrip("\n") for ln in open(in_file, "r", errors="ignore")]
    except FileNotFoundError:
        print(f"Errore: Il file di input '{in_file}' non è stato trovato.")
        sys.exit(1)
        
    events = parse_events(lines)
    
    with open(out_file, "w") as out:
        out.write("IPOSTRINGA LAT LON DEPTH N_P N_S RMS_HE RMS_W RMS_UW SEH SEZ GAP\n")
        for ev in events:
            out.write(
                f'{ev["IPOSTRINGA"]} '
                f'{ev["LAT"]:.5f} {ev["LON"]:.5f} '
                f'{ev["DEPTH"]:.2f} '
                f'{ev["N_P"]} {ev["N_S"]} '
                f'{ev["RMS_HE"]:.4f} '
                f'{(ev["RMS_W"] if math.isfinite(ev["RMS_W"]) else -999.99):.4f} '
                f'{(ev["RMS_UW"] if math.isfinite(ev["RMS_UW"]) else -999.99):.4f} '
                f'{(ev["SEH"] if math.isfinite(ev["SEH"]) else -999.99):.2f} '
                f'{(ev["SEZ"] if math.isfinite(ev["SEZ"]) else -999.99):.2f} '
                f'{ev["GAP"]}\n'
            )
    print(f"Wrote {len(events)} events to {out_file}")

if __name__ == "__main__":
    # Percorsi di default come da codice originale
    default_in = "/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/RELOC_HYPOELLIPSE/location-1D.out"
    default_out = "/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/RELOC_HYPOELLIPSE/location-1D.quality"

    if len(sys.argv) < 3:
        in_file, out_file = default_in, default_out
    else:
        in_file, out_file = sys.argv[1], sys.argv[2]

    main(in_file, out_file)
