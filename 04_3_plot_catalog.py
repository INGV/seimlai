import pygmt
import pandas as pd
import os

# Configurazione percorsi
year, dayini, dayfin = 2016, 294, 306
base_dir = "/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog"
#output_dir = f"{base_dir}/PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_transferlearning_crossentropy_/output/output_catalog_09-09"
#output_dir="/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_focalloss_/output/output_catalog_09-09"
#output_dir = f"{base_dir}/EP_41_PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_crossentropy_/output/output_catalog_09-09"
#output_dir="/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_transferlearning_crossentropy_/output_03P_02S_PN_60_epochs_1024_bs_0.0005_lr_std_norm.AQ2009_transferlearning_crossentropy_/output_catalog/"
output_dir="/Users/rossella.fonzetti/WORK/EPOS/TRAINING_AQ2009/GFZ_TESTS/Amatrice_catalog/PN_60_epochs_4096_bs_0.0001_lr_std_norm.AQ2009_transferlearning_focalloss_20250627_143520_/output/output_catalog/"
topo_grid = "/Users/rossella.fonzetti/WORK/TOPO/italy_srtm.grd"

# Caricamento dati salvati dallo script precedente
catalog_file = os.path.join(output_dir, f"seismic_catalog_with_latlon_{year}_{dayini}_{dayfin}.csv")
stations_file = os.path.join(output_dir, "stations_processed.csv")

if not os.path.exists(catalog_file):
    print(f"Errore: Il file {catalog_file} non esiste. Esegui prima lo script di elaborazione.")
    exit()

catalog = pd.read_csv(catalog_file)
station_df = pd.read_csv(stations_file)

# --- Inizio Plotting PyGMT ---
os.environ["GMT_LIBRARY_PATH"] = "/Applications/gmt-6.5.0-darwin-arm64/GMT-6.5.0.app/Contents/Resources/lib/"
pygmt.config(GMT_VERBOSE="q")
region = [12.5, 14.00, 42.00, 43.50]

fig = pygmt.Figure()

# Topografia
pygmt.makecpt(
    cmap="gray",
    series=[-1000, 3000],
    truncate="0.4/1.0",
    continuous=True
)


fig.grdimage(
    grid=topo_grid,
    region=region,
    projection="M6i",
    shading="+a135+nt0.6",
    cmap=True,
    frame=["af", '+t"Central Italy - 2016/10/30 Seismicity"']
)

fig.coast(shorelines="1/0.25p,black", resolution="h")

# Terremoti
pygmt.makecpt(
    cmap="viridis",
    series=[catalog["z(km)"].min(), catalog["z(km)"].max(), 1],
    continuous=True
)

fig.plot(
    x=catalog["longitude"],
    y=catalog["latitude"],
    style="c0.06c",
    fill=catalog["z(km)"],
    cmap=True,
    pen=False,            
    transparency=20
)

# Stazioni
fig.plot(
    x=station_df["longitude"],
    y=station_df["latitude"],
    style="t0.25c",
    fill="red",
    pen="black"
)

fig.colorbar(position="JBC+o2.0c/1.4c+w8c/0.4c+h", frame='af+l"Depth (km)"')
fig.basemap(map_scale="jBL+o0.3c/-1.5c+w10k+f+l")

# Inset Italy
with fig.inset(position="jTR+w3.5c+o0.3c", box="+gwhite+p1p,black"):
    fig.coast(region=[8, 17, 40.5, 47], projection="M3.5c", land="gray85", water="white", shorelines="0.25p,black")
    rect = [[region[0], region[2]], [region[1], region[2]], [region[1], region[3]], [region[0], region[3]], [region[0], region[2]]]
    fig.plot(data=rect, pen="1p,red")

# Save and Show
output_pdf = os.path.join(output_dir, f"map_catalog_{year}_{dayini}_{dayfin}.pdf")
fig.savefig(output_pdf, dpi=300)
fig.show()
print(f"Mappa salvata in: {output_pdf}")
