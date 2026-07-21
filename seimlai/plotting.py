#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Nov 13 10:47:52 2025

@author: rossella.fonzetti
"""
import os

import pygmt
import pandas as pd

def run(ctx):
    globals().update(ctx.legacy_globals())

    # Set GMT library path before importing pygmt
    if GMT_LIBRARY_PATH:
        os.environ["GMT_LIBRARY_PATH"] = GMT_LIBRARY_PATH

    # --- Derived paths from runtime context ---
    catalog_file = os.path.join(output_dir, f"seismic_catalog_with_latlon_{year}_{start_day}_{end_day}.csv")
    stations_file = stations_csv_path

    if not os.path.exists(catalog_file):
        print(f"Error: The file {catalog_file} does not exist. Run the processing script first.")
        return

    catalog = pd.read_csv(catalog_file)
    station_df = pd.read_csv(stations_file)

    pygmt.config(GMT_VERBOSE="q")

    fig = pygmt.Figure()

    pygmt.makecpt(
        cmap="gray",
        series=[-1000, 3000],
        truncate="0.4/1.0",
        continuous=True
    )

    fig.grdimage(
        grid=GMT_GRID_PATH,
        region=plot_region,
        projection="M6i",
        shading="+a135+nt0.6",
        cmap=True,
        frame=["af", f'+t"{plot_map_title}"']
    )

    fig.coast(shorelines="1/0.25p,black", resolution="h")

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

    fig.plot(
        x=station_df["longitude"],
        y=station_df["latitude"],
        style="t0.25c",
        fill="red",
        pen="black"
    )

    fig.colorbar(position="JBC+o2.0c/1.4c+w8c/0.4c+h", frame='af+l"Depth (km)"')
    fig.basemap(map_scale="jBL+o0.3c/-1.5c+w10k+f+l")

    with fig.inset(position="jTR+w3.5c+o0.3c", box="+gwhite+p1p,black"):
        fig.coast(region=[8, 17, 40.5, 47], projection="M3.5c", land="gray85", water="white", shorelines="0.25p,black")
        rect = [
            [plot_region[0], plot_region[2]],
            [plot_region[1], plot_region[2]],
            [plot_region[1], plot_region[3]],
            [plot_region[0], plot_region[3]],
            [plot_region[0], plot_region[2]],
        ]
        fig.plot(data=rect, pen="1p,red")

    output_pdf = os.path.join(output_dir, f"map_catalog_{year}_{start_day}_{end_day}.pdf")
    fig.savefig(output_pdf, dpi=300)
    fig.show()
    print(f"Mappa salvata in: {output_pdf}")


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_plotting = run


if __name__ == "__main__":
    main()
