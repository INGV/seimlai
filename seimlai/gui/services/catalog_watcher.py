"""Catalog and station watcher service for SeiMLAI GUI.

Watches output folders for newly generated station metadata and earthquake catalogs
(GaMMA, HypoEllipse, HypoDD) and parses them for live interactive mapping.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable

import pandas as pd

from seimlai.context import build_context


@dataclass
class StationItem:
    network: str
    station: str
    latitude: float
    longitude: float
    elevation: float | None = None
    location: str = ""


@dataclass
class EarthquakeItem:
    id: str | int
    latitude: float
    longitude: float
    depth_km: float
    magnitude: float | None
    time_str: str | None
    source: str  # "gamma", "hypoellipse", "hypodd"
    extra: dict[str, Any] | None = None


class CatalogWatcher:
    """Monitors workflow output files and emits structured stations and earthquake catalogs."""

    def __init__(self, config_path: str = "user_configuration/config.yaml"):
        self.config_path = config_path
        self._lock = threading.Lock()
        self.stations: list[StationItem] = []
        self.catalogs: dict[str, list[EarthquakeItem]] = {
            "gamma": [],
            "hypoellipse": [],
            "hypodd": [],
        }
        self.active_source: str = "gamma"

        self._file_mtimes: dict[str, float] = {}
        self._refresh_lock = threading.Lock()
        self._case_root: Path | None = None
        self._listeners: list[Callable[[str, list[Any]], None]] = []
        self._is_watching = False
        self._watch_thread: threading.Thread | None = None

        # Initial check
        self.refresh()

    def add_listener(self, cb: Callable[[str, list[Any]], None]) -> None:
        """Add listener for ('stations' | 'catalog', items)."""
        self._listeners.append(cb)

    def _notify(self, event_type: str, items: list[Any]) -> None:
        for cb in self._listeners:
            try:
                cb(event_type, items)
            except Exception:
                pass

    def start_watching(self, poll_interval_seconds: float = 2.0) -> None:
        """Start background polling thread to watch output directory changes."""
        if self._is_watching:
            return
        self._is_watching = True
        self._watch_thread = threading.Thread(
            target=self._poll_loop,
            args=(poll_interval_seconds,),
            daemon=True,
        )
        self._watch_thread.start()

    def stop_watching(self) -> None:
        self._is_watching = False

    def _poll_loop(self, interval: float) -> None:
        while self._is_watching:
            try:
                self.refresh()
            except Exception:
                pass
            time.sleep(interval)

    def refresh(self) -> None:
        """Scan current paths according to current config and parse new or modified files."""
        with self._refresh_lock:
            self._refresh()

    def _refresh(self) -> None:
        try:
            ctx = build_context(self.config_path)
        except Exception:
            return

        case_root = ctx.paths.project_root.resolve()
        if case_root != self._case_root:
            with self._lock:
                self.stations = []
                self.catalogs = {"gamma": [], "hypoellipse": [], "hypodd": []}
                self._file_mtimes.clear()
                self._case_root = case_root
            self._notify("stations", [])
            self._notify("catalog", [])

        # 1. Check Stations file
        sta_path = ctx.paths.stations_csv_path
        if sta_path.exists():
            mtime = sta_path.stat().st_mtime
            if self._file_mtimes.get(str(sta_path)) != mtime:
                self._file_mtimes[str(sta_path)] = mtime
                self._load_stations(sta_path)

        # 2. Check GaMMA catalog
        # Pattern in gamma_dir: seismic_catalog_with_latlon_*.csv
        gamma_dir = ctx.paths.gamma_dir
        if gamma_dir.exists():
            for p in gamma_dir.glob("seismic_catalog_with_latlon_*.csv"):
                mtime = p.stat().st_mtime
                if self._file_mtimes.get(str(p)) != mtime:
                    self._file_mtimes[str(p)] = mtime
                    self._load_gamma_catalog(p)

        # 3. Check HypoEllipse filtered/quality files
        he_dir = ctx.paths.hypoellipse_output_dir
        if he_dir.exists():
            for p in he_dir.glob("location-1D_*.quality"):
                mtime = p.stat().st_mtime
                if self._file_mtimes.get(str(p)) != mtime:
                    self._file_mtimes[str(p)] = mtime
                    self._load_hypoellipse_quality(p)
            for p in he_dir.glob("filtered_locations_*.csv"):
                mtime = p.stat().st_mtime
                if self._file_mtimes.get(str(p)) != mtime:
                    self._file_mtimes[str(p)] = mtime
                    self._load_hypoellipse_filtered_csv(p)

        # 4. Check HypoDD relocated catalog
        hd_path = ctx.paths.hypodd_reloc_path
        if hd_path.exists():
            mtime = hd_path.stat().st_mtime
            if self._file_mtimes.get(str(hd_path)) != mtime:
                self._file_mtimes[str(hd_path)] = mtime
                self._load_hypodd_reloc(hd_path)

    def _load_stations(self, path: Path) -> None:
        try:
            df = pd.read_csv(path)
            items: list[StationItem] = []
            for _, r in df.iterrows():
                try:
                    lat = float(r.get("latitude", r.get("lat", 0)))
                    lon = float(r.get("longitude", r.get("lon", 0)))
                    elev = float(r["elevation"]) if "elevation" in r and pd.notna(r["elevation"]) else None
                    items.append(
                        StationItem(
                            network=str(r.get("network", "")),
                            station=str(r.get("station", "")),
                            latitude=lat,
                            longitude=lon,
                            elevation=elev,
                            location=str(r.get("location", "")),
                        )
                    )
                except Exception:
                    continue
            with self._lock:
                self.stations = items
            self._notify("stations", self.stations)
        except Exception:
            pass

    def _load_gamma_catalog(self, path: Path) -> None:
        try:
            df = pd.read_csv(path)
            items: list[EarthquakeItem] = []
            for idx, r in df.iterrows():
                try:
                    lat = float(r.get("latitude", r.get("lat", 0)))
                    lon = float(r.get("longitude", r.get("lon", 0)))
                    # GaMMA might output depth(m) or depth in km
                    depth = 0.0
                    if "z(km)" in r:
                        depth = float(r["z(km)"])
                    elif "depth(m)" in r:
                        depth = float(r["depth(m)"]) / 1000.0
                    elif "depth" in r:
                        depth = float(r["depth"])
                        if depth > 1000:  # If in meters
                            depth /= 1000.0

                    mag = float(r["magnitude"]) if "magnitude" in r and pd.notna(r["magnitude"]) else None
                    time_val = str(r.get("time", ""))
                    ev_id = str(r.get("event_idx", r.get("id", idx)))

                    items.append(
                        EarthquakeItem(
                            id=ev_id,
                            latitude=lat,
                            longitude=lon,
                            depth_km=round(depth, 2),
                            magnitude=round(mag, 1) if mag is not None else None,
                            time_str=time_val,
                            source="gamma",
                        )
                    )
                except Exception:
                    continue
            with self._lock:
                self.catalogs["gamma"] = items
            self._notify("catalog", items)
        except Exception:
            pass

    def _load_hypoellipse_quality(self, path: Path) -> None:
        # Output columns: IPOSTRINGA LAT LON DEPTH N_P N_S RMS_HE RMS_W RMS_UW SEH SEZ GAP
        try:
            items: list[EarthquakeItem] = []
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter=" ")
                header = next(reader, None)
                for row in reader:
                    parts = [p for p in row if p]
                    if len(parts) < 4:
                        continue
                    try:
                        ev_id = parts[0]
                        lat = float(parts[1])
                        lon = float(parts[2])
                        depth = float(parts[3])
                        rms = float(parts[7]) if len(parts) > 7 else None
                        gap = float(parts[11]) if len(parts) > 11 else None
                        items.append(
                            EarthquakeItem(
                                id=ev_id,
                                latitude=lat,
                                longitude=lon,
                                depth_km=round(depth, 2),
                                magnitude=None,
                                time_str=None,
                                source="hypoellipse",
                                extra={"rms": rms, "gap": gap},
                            )
                        )
                    except Exception:
                        continue
            if items:
                with self._lock:
                    self.catalogs["hypoellipse"] = items
                self._notify("catalog", items)
        except Exception:
            pass

    def _load_hypoellipse_filtered_csv(self, path: Path) -> None:
        try:
            df = pd.read_csv(path)
            items: list[EarthquakeItem] = []
            for idx, r in df.iterrows():
                try:
                    lat = float(r.get("lat", r.get("LAT", r.get("latitude", 0))))
                    lon = float(r.get("lon", r.get("LON", r.get("longitude", 0))))
                    depth = float(r.get("depth", r.get("DEPTH", 0)))
                    mag = float(r["mag"]) if "mag" in r and pd.notna(r["mag"]) else None
                    ev_id = str(r.get("ID", r.get("event_idx", idx)))
                    items.append(
                        EarthquakeItem(
                            id=ev_id,
                            latitude=lat,
                            longitude=lon,
                            depth_km=round(depth, 2),
                            magnitude=round(mag, 1) if mag is not None else None,
                            time_str=None,
                            source="hypoellipse",
                        )
                    )
                except Exception:
                    continue
            if items:
                with self._lock:
                    self.catalogs["hypoellipse"] = items
                self._notify("catalog", items)
        except Exception:
            pass

    def _load_hypodd_reloc(self, path: Path) -> None:
        try:
            # Header: # ID LAT LON DEPTH X Y Z EX EY EZ YEAR MONTH DAY HOUR MIN SEC MAG ...
            df = pd.read_csv(path, sep=r"\s+", comment="#", names=[
                "ID", "LAT", "LON", "DEPTH", "X", "Y", "Z", "EX", "EY", "EZ",
                "YEAR", "MONTH", "DAY", "HOUR", "MIN", "SEC", "MAG"
            ], usecols=range(17))

            items: list[EarthquakeItem] = []
            for _, r in df.iterrows():
                try:
                    lat = float(r["LAT"])
                    lon = float(r["LON"])
                    depth = float(r["DEPTH"])
                    mag = float(r["MAG"]) if "MAG" in r and pd.notna(r["MAG"]) and float(r["MAG"]) != -9.0 else None
                    date_parts = f"{int(r['YEAR']):04d}-{int(r['MONTH']):02d}-{int(r['DAY']):02d} {int(r['HOUR']):02d}:{int(r['MIN']):02d}:{float(r['SEC']):04.1f}"
                    items.append(
                        EarthquakeItem(
                            id=str(r["ID"]),
                            latitude=lat,
                            longitude=lon,
                            depth_km=round(depth, 2),
                            magnitude=round(mag, 1) if mag is not None else None,
                            time_str=date_parts,
                            source="hypodd",
                        )
                    )
                except Exception:
                    continue
            with self._lock:
                self.catalogs["hypodd"] = items
            self._notify("catalog", items)
        except Exception:
            pass

    def get_active_catalog(self) -> list[EarthquakeItem]:
        """Return earthquakes for the active source."""
        with self._lock:
            return list(self.catalogs.get(self.active_source, []))

