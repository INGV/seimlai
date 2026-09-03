#!/usr/bin/env python3
"""Plot all and quality-filtered HypoEllipse locations in GaMMA's map style."""

from pathlib import Path
import os

import pandas as pd
import pygmt


def _gamma_catalog_path() -> Path:
    current = Path(output_dir) / f"seismic_catalog_with_latlon_{date_tag}.csv"
    if current.exists():
        return current
    legacy = Path(output_dir) / f"seismic_catalog_with_latlon_{year}_{start_day}_{end_day}.csv"
    if legacy.exists():
        return legacy
    raise FileNotFoundError(f"GaMMA catalog not found: {current}")


def _gamma_depth_range(gamma_catalog: pd.DataFrame) -> tuple[float, float]:
    depth = pd.to_numeric(gamma_catalog["z(km)"], errors="coerce").dropna()
    if depth.empty:
        raise ValueError("GaMMA catalog has no valid 'z(km)' depths")
    minimum, maximum = float(depth.min()), float(depth.max())
    return (minimum, maximum if maximum > minimum else minimum + 1.0)


def _plot_catalog(
    catalog: pd.DataFrame,
    stations: pd.DataFrame,
    depth_range: tuple[float, float],
    title: str,
    output_path: Path,
) -> None:
    """Draw one map with the visual settings shared with the GaMMA plot."""
    pygmt.config(GMT_VERBOSE="q")
    figure = pygmt.Figure()
    pygmt.makecpt(cmap="gray", series=[-1000, 3000], truncate="0.4/1.0", continuous=True)
    figure.grdimage(
        grid=GMT_GRID_PATH,
        region=plot_region,
        projection="M6i",
        shading="+a135+nt0.6",
        cmap=True,
        frame=["af", f'+t"{title}"'],
    )
    figure.coast(shorelines="1/0.25p,black", resolution="h")
    # Use GaMMA's depth limits in both figures: colours are directly comparable.
    pygmt.makecpt(cmap="viridis", series=[*depth_range, 1], continuous=True)
    figure.plot(
        x=catalog["LON"],
        y=catalog["LAT"],
        style="c0.06c",
        fill=catalog["DEPTH"],
        cmap=True,
        pen=False,
        transparency=20,
    )
    figure.plot(
        x=stations["longitude"],
        y=stations["latitude"],
        style="t0.25c",
        fill="red",
        pen="black",
    )
    figure.colorbar(position="JBC+o2.0c/1.4c+w8c/0.4c+h", frame='af+l"Depth (km)"')
    figure.basemap(map_scale="jBL+o0.3c/-1.5c+w10k+f+l")
    with figure.inset(position="jTR+w3.5c+o0.3c", box="+gwhite+p1p,black"):
        figure.coast(
            region=[8, 17, 40.5, 47],
            projection="M3.5c",
            land="gray85",
            water="white",
            shorelines="0.25p,black",
        )
        rectangle = [
            [plot_region[0], plot_region[2]],
            [plot_region[1], plot_region[2]],
            [plot_region[1], plot_region[3]],
            [plot_region[0], plot_region[3]],
            [plot_region[0], plot_region[2]],
        ]
        figure.plot(data=rectangle, pen="1p,red")

    figure.savefig(output_path, dpi=300)
    figure.show()
    print(f"HypoEllipse map saved to: {output_path}")


def run(ctx):
    """Generate both the complete and quality-filtered HypoEllipse maps."""
    globals().update(ctx.legacy_globals())
    if GMT_LIBRARY_PATH:
        os.environ["GMT_LIBRARY_PATH"] = GMT_LIBRARY_PATH

    quality_path = Path(location_1d_quality_path)
    if not quality_path.exists():
        raise FileNotFoundError(
            f"HypoEllipse quality file not found: {quality_path}. Run step 07 first."
        )

    catalog = pd.read_csv(quality_path, sep=r"\s+")
    required = {"LAT", "LON", "DEPTH", "GAP", "RMS_HE", "SEH", "SEZ"}
    missing = required.difference(catalog.columns)
    if missing:
        raise ValueError(f"Unexpected HypoEllipse quality schema; missing {sorted(missing)}")
    for column in required:
        catalog[column] = pd.to_numeric(catalog[column], errors="coerce")
    catalog = catalog.dropna(subset=["LAT", "LON", "DEPTH"])
    if catalog.empty:
        raise ValueError("HypoEllipse quality file contains no mappable locations")

    filtered = catalog.loc[
        (catalog["GAP"] < DD_MAX_GAP)
        & (catalog["RMS_HE"] < DD_MAX_RMS)
        & (catalog["SEH"] < DD_MAX_ERH)
        & (catalog["SEZ"] < DD_MAX_ERZ)
    ].copy()

    gamma_catalog = pd.read_csv(_gamma_catalog_path())
    depth_range = _gamma_depth_range(gamma_catalog)
    stations = pd.read_csv(stations_csv_path)
    output_directory = Path(hypoellipse_output_dir)

    _plot_catalog(
        catalog,
        stations,
        depth_range,
        f"{plot_map_title} (HypoEllipse, all locations)",
        output_directory / f"map_hypoellipse_all_{date_tag}.pdf",
    )
    if filtered.empty:
        print("No events pass the current quality filters; filtered map was not created.")
        return
    _plot_catalog(
        filtered,
        stations,
        depth_range,
        f"{plot_map_title} (HypoEllipse, filtered)",
        output_directory / f"map_hypoellipse_filtered_{date_tag}.pdf",
    )
    print(f"HypoEllipse events: {len(catalog):,} total; {len(filtered):,} filtered")


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_hypoellipse_plotting = run

