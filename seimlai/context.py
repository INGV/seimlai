from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RawConfig:
    case_study: dict[str, Any]
    geography: dict[str, Any]
    dates: dict[str, Any]
    stations: dict[str, Any]
    model: dict[str, Any]
    gamma: dict[str, Any]
    analysis: dict[str, Any]
    plotting: dict[str, Any]
    hypoellipse: dict[str, Any]
    dd: dict[str, Any]
    script11: dict[str, Any]
    script12: dict[str, Any]


@dataclass(frozen=True)
class Paths:
    base_dir: Path
    project_root: Path
    root_dir: Path
    inventory_dir: Path
    waveform_base: Path
    output_base: Path
    output_picks_dir: Path
    output_dir: Path
    h71_filtered_dir: Path
    dd_dir: Path
    download_log_path: Path
    log_file_path: Path
    location_1d_out_path: Path
    location_1d_quality_path: Path
    filtered_locations_csv_path: Path
    filtered_phases_csv_path: Path
    phs_file_path: Path
    stations_csv_path: Path
    dd_output_file: Path
    dd_station_file: Path
    dd_dtcc_file: Path
    csv_filename_12: str
    output_bar_path_12: Path
    output_line_path_12: Path
    station_file_name: str = "stations.csv"


@dataclass(frozen=True)
class DerivedConfig:
    start_day: int
    end_day: int
    thr: str
    gamma_config: dict[str, Any]


@dataclass
class RuntimeContext:
    raw: RawConfig
    paths: Paths
    derived: DerivedConfig
    config_path: Path

    @cached_property
    def starttime(self):
        from obspy import UTCDateTime

        return UTCDateTime(self.raw.dates["starttime"])

    @cached_property
    def endtime(self):
        from obspy import UTCDateTime

        return UTCDateTime(self.raw.dates["endtime"])

    @cached_property
    def device(self):
        import torch

        if torch.backends.mps.is_available():
            return torch.device("mps"), "MPS (Apple Silicon GPU)"
        if torch.cuda.is_available():
            return torch.device("cuda"), torch.cuda.get_device_name(0)
        return torch.device("cpu"), "CPU"

    @cached_property
    def phasenet_model(self):
        import torch
        from seisbench.models import EQTransformer, PhaseNet

        device, _ = self.device
        model_cfg = self.raw.model
        network_choice = str(model_cfg["neural_network"]).lower()
        custom_model_path = model_cfg.get("custom_model_path")

        if custom_model_path is not None:
            if network_choice == "eqtransformer":
                model = EQTransformer()
            else:
                model = PhaseNet()
                model.labels = "PSN"

            checkpoint = torch.load(custom_model_path, map_location=device)
            if "model_state_dict" in checkpoint:
                model.load_state_dict(checkpoint["model_state_dict"])
            else:
                model.load_state_dict(checkpoint)
            print(f"Custom model loaded from: {custom_model_path}")
        else:
            model_type = model_cfg["model_type"]
            if network_choice == "eqtransformer":
                model = EQTransformer.from_pretrained(model_type)
                print(f"Pretrained model loaded: EQTransformer '{model_type}'")
            else:
                model = PhaseNet.from_pretrained(model_type)
                print(f"Pretrained model loaded: PhaseNet '{model_type}'")

        model.to(device)
        model.eval()
        return model

    @cached_property
    def transformer(self):
        from pyproj import CRS, Transformer

        wgs84 = CRS.from_epsg(4326)
        utm33n = CRS.from_epsg(32633)
        return wgs84, utm33n, Transformer.from_crs(wgs84, utm33n, always_xy=True)

    @cached_property
    def fdsn_clients(self):
        from obspy.clients.fdsn import Client

        clients = []
        for provider in self.raw.stations["fdsn_clients"]:
            try:
                clients.append(Client(provider))
            except Exception as e:
                print(f"Warning: Could not connect to {provider} FDSN service: {e}")
        return clients

    def get_fdsn_clients(self):
        return list(self.fdsn_clients)

    def legacy_globals(
        self,
        *,
        include_model: bool = False,
        include_device: bool = False,
        include_geo: bool = False,
        include_fdsn: bool = False,
    ) -> dict[str, Any]:
        model_cfg = self.raw.model
        plotting_cfg = self.raw.plotting
        script11_cfg = self.raw.script11
        legacy = {
            "case_study_name": self.raw.case_study["name"],
            "PERSONAL_FOLDER": self.raw.case_study["personal_folder"],
            "DOWNLOAD_DATA": self.raw.case_study["download_data"],
            "minlatitude": self.raw.geography["minlatitude"],
            "maxlatitude": self.raw.geography["maxlatitude"],
            "minlongitude": self.raw.geography["minlongitude"],
            "maxlongitude": self.raw.geography["maxlongitude"],
            "starttime": self.starttime,
            "endtime": self.endtime,
            "year": self.raw.dates["year"],
            "network": self.raw.stations["network"],
            "channel": self.raw.stations["channel"],
            "stations_list": self.raw.stations["stations_list"],
            "fdsn_clients": self.raw.stations["fdsn_clients"],
            "NEURAL_NETWORK": model_cfg["neural_network"],
            "MODEL_TYPE": model_cfg["model_type"],
            "CUSTOM_MODEL_PATH": model_cfg["custom_model_path"],
            "BATCH_SIZE": model_cfg["batch_size"],
            "P_THRESHOLD": model_cfg["p_threshold"],
            "S_THRESHOLD": model_cfg["s_threshold"],
            "WLENGTH_SECONDS": model_cfg["wlength_seconds"],
            "start_day": self.derived.start_day,
            "end_day": self.derived.end_day,
            "THR": self.derived.thr,
            "config": self.derived.gamma_config,
            "analysis_log_filename": self.raw.analysis["log_filename"],
            "GMT_LIBRARY_PATH": os.environ.get("GMT_LIBRARY_PATH", plotting_cfg["gmt_library_path"]),
            "GMT_GRID_PATH": os.environ.get("GMT_GRID_PATH", plotting_cfg["gmt_grid_path"]),
            "plot_region": plotting_cfg["region"],
            "plot_map_title": plotting_cfg["map_title"],
            "h71_min_p": self.raw.hypoellipse["h71_min_p"],
            "h71_min_s": self.raw.hypoellipse["h71_min_s"],
            "DD_MAX_GAP": self.raw.dd["max_gap"],
            "DD_MAX_RMS": self.raw.dd["max_rms"],
            "DD_MAX_ERH": self.raw.dd["max_erh"],
            "DD_MAX_ERZ": self.raw.dd["max_erz"],
            "MAX_DIST_KM_CC": script11_cfg["max_dist_km_cc"],
            "CC_THRESHOLD_11": script11_cfg["cc_threshold"],
            "WIN_BEFORE_CC": script11_cfg["win_before"],
            "WIN_AFTER_CC": script11_cfg["win_after"],
            "CC_MAX_LAG_11": script11_cfg["cc_max_lag"],
            "FREQ_MIN_CC": script11_cfg["freq_min"],
            "FREQ_MAX_CC": script11_cfg["freq_max"],
            "CC_NETWORK": script11_cfg["network"],
            "THRESHOLDS_MAP_12": self.raw.script12["thresholds_map"],
            "base_dir": str(self.paths.base_dir),
            "project_root": str(self.paths.project_root),
            "case_study_dir": str(self.paths.project_root),
            "root_dir": str(self.paths.root_dir),
            "inventory_dir": str(self.paths.inventory_dir),
            "waveform_base": str(self.paths.waveform_base),
            "output_base": str(self.paths.output_base),
            "output_picks_dir": str(self.paths.output_picks_dir),
            "output_dir": str(self.paths.output_dir),
            "h71_filtered_dir": str(self.paths.h71_filtered_dir),
            "dd_dir": str(self.paths.dd_dir),
            "download_log_path": str(self.paths.download_log_path),
            "station_file_name": self.paths.station_file_name,
            "log_file_path": str(self.paths.log_file_path),
            "location_1d_out_path": str(self.paths.location_1d_out_path),
            "location_1d_quality_path": str(self.paths.location_1d_quality_path),
            "filtered_locations_csv_path": str(self.paths.filtered_locations_csv_path),
            "filtered_phases_csv_path": str(self.paths.filtered_phases_csv_path),
            "phs_file_path": str(self.paths.phs_file_path),
            "stations_csv_path": str(self.paths.stations_csv_path),
            "dd_output_file": str(self.paths.dd_output_file),
            "dd_station_file": str(self.paths.dd_station_file),
            "dd_dtcc_file": str(self.paths.dd_dtcc_file),
            "CSV_FILENAME_12": self.paths.csv_filename_12,
            "output_bar_path_12": str(self.paths.output_bar_path_12),
            "output_line_path_12": str(self.paths.output_line_path_12),
        }
        if include_device:
            legacy["device"], legacy["device_name"] = self.device
        if include_model:
            legacy["model"] = self.phasenet_model
        if include_geo:
            legacy["wgs84"], legacy["utm33n"], legacy["transformer"] = self.transformer
        if include_fdsn:
            legacy["get_fdsn_clients"] = self.get_fdsn_clients
        return legacy


def load_config(path: str | Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is required to read config.yaml. Activate the Conda environment "
            "or run `conda env update -f environment.yml`."
        ) from exc

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file {path} must contain a YAML mapping.")
    return data


def validate_config(raw: dict[str, Any]) -> None:
    required = {
        "case_study": ["name", "personal_folder", "download_data"],
        "geography": ["minlatitude", "maxlatitude", "minlongitude", "maxlongitude"],
        "dates": ["starttime", "endtime", "year"],
        "stations": ["network", "channel", "stations_list", "fdsn_clients"],
        "model": ["neural_network", "model_type", "custom_model_path", "batch_size", "p_threshold", "s_threshold", "wlength_seconds"],
        "gamma": ["dims", "use_dbscan", "use_amplitude", "x_km", "y_km", "z_km", "velocity", "method", "dbscan_eps", "dbscan_min_samples", "eikonal", "filtering"],
        "analysis": ["log_filename"],
        "plotting": ["gmt_library_path", "gmt_grid_path", "region", "map_title"],
        "hypoellipse": ["h71_min_p", "h71_min_s", "velocity_model_path", "parameter_file_path"],
        "dd": ["max_gap", "max_rms", "max_erh", "max_erz"],
        "script11": ["max_dist_km_cc", "cc_threshold", "win_before", "win_after", "cc_max_lag", "freq_min", "freq_max", "network"],
        "script12": ["thresholds_map"],
    }
    missing = []
    for section, keys in required.items():
        if section not in raw or not isinstance(raw[section], dict):
            missing.append(section)
            continue
        for key in keys:
            if key not in raw[section]:
                missing.append(f"{section}.{key}")

    nested = [
        ("gamma.velocity", ["p", "s"]),
        ("gamma.eikonal", ["z", "p", "vp_vs_ratio", "h"]),
        ("gamma.filtering", ["min_picks_per_eq", "min_p_picks_per_eq", "min_s_picks_per_eq", "max_sigma11", "max_sigma22", "max_sigma12"]),
    ]
    for dotted, keys in nested:
        section, child = dotted.split(".")
        value = raw.get(section, {}).get(child)
        if not isinstance(value, dict):
            missing.append(dotted)
            continue
        for key in keys:
            if key not in value:
                missing.append(f"{dotted}.{key}")

    if missing:
        raise ValueError("Missing configuration keys: " + ", ".join(missing))


def build_context(config_path: str | Path = "config.yaml") -> RuntimeContext:
    config_path = Path(config_path)
    raw_dict = load_config(config_path)
    validate_config(raw_dict)
    raw = RawConfig(**raw_dict)

    from obspy import UTCDateTime

    starttime = UTCDateTime(raw.dates["starttime"])
    endtime = UTCDateTime(raw.dates["endtime"])
    p_threshold = raw.model["p_threshold"]
    s_threshold = raw.model["s_threshold"]
    thr = f"{int(p_threshold * 10):02d}-{int(s_threshold * 10):02d}"

    base_dir = Path.cwd()
    project_root = Path(raw.case_study["personal_folder"]) if raw.case_study["personal_folder"] else base_dir / raw.case_study["name"]
    output_base = project_root / "output"
    output_dir = output_base / f"output_catalog_{p_threshold}"
    h71_filtered_dir = output_dir / "filtered_data"
    dd_dir = output_dir / "refined_localizations"
    station_file_name = "stations.csv"

    paths = Paths(
        base_dir=base_dir,
        project_root=project_root,
        root_dir=project_root / "waveforms",
        inventory_dir=project_root / "inventory",
        waveform_base=project_root / "waveforms" / str(raw.dates["year"]),
        output_base=output_base,
        output_picks_dir=output_base / f"output_picks_{p_threshold}",
        output_dir=output_dir,
        h71_filtered_dir=h71_filtered_dir,
        dd_dir=dd_dir,
        download_log_path=project_root / "download_log.txt",
        log_file_path=output_base / "phase_picking_log.txt",
        location_1d_out_path=dd_dir / "location-1D.out",
        location_1d_quality_path=dd_dir / f"location-1D_{thr}.quality",
        filtered_locations_csv_path=dd_dir / f"filtered_locations_{thr}.csv",
        filtered_phases_csv_path=dd_dir / f"filtered_phases_{thr}.csv",
        phs_file_path=h71_filtered_dir / "out_conv.phs",
        stations_csv_path=project_root / station_file_name,
        dd_output_file=dd_dir / f"travel_{thr}.dat",
        dd_station_file=dd_dir / f"station_{thr}.dat",
        dd_dtcc_file=dd_dir / "dt.cc",
        csv_filename_12=f"seismic_catalog_with_latlon_{raw.dates['year']}_{starttime.julday:03d}_{endtime.julday:03d}.csv",
        output_bar_path_12=output_base / "grouped_bar_charts.pdf",
        output_line_path_12=output_base / "line_charts_vs_THR.pdf",
        station_file_name=station_file_name,
    )

    gamma_config = _build_gamma_config(raw.gamma)
    derived = DerivedConfig(
        start_day=starttime.julday,
        end_day=endtime.julday,
        thr=thr,
        gamma_config=gamma_config,
    )
    return RuntimeContext(raw=raw, paths=paths, derived=derived, config_path=config_path)


def ensure_initial_directories(ctx: RuntimeContext) -> None:
    """Create directories expected before external/manual workflow steps."""
    for path in (
        ctx.paths.project_root,
        ctx.paths.output_base,
        ctx.paths.output_dir,
        ctx.paths.dd_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _build_gamma_config(gamma: dict[str, Any]) -> dict[str, Any]:
    xlim = tuple(gamma["x_km"])
    ylim = tuple(gamma["y_km"])
    zlim = tuple(gamma["z_km"])
    method = gamma["method"]
    eikonal = gamma["eikonal"]
    filtering = gamma["filtering"]

    vp = list(eikonal["p"])
    vs = [v / eikonal["vp_vs_ratio"] for v in vp]
    gamma_config = {
        "dims": list(gamma["dims"]),
        "use_dbscan": gamma["use_dbscan"],
        "use_amplitude": gamma["use_amplitude"],
        "x(km)": xlim,
        "y(km)": ylim,
        "z(km)": zlim,
        "vel": dict(gamma["velocity"]),
        "method": method,
        "oversample_factor": 4 if method == "BGMM" else 1,
        "bfgs_bounds": (
            (xlim[0] - 1, xlim[1] + 1),
            (ylim[0] - 1, ylim[1] + 1),
            (0, zlim[1] + 1),
            (None, None),
        ),
        "dbscan_eps": gamma["dbscan_eps"],
        "dbscan_min_samples": gamma["dbscan_min_samples"],
        "eikonal": {
            "vel": {"z": list(eikonal["z"]), "p": vp, "s": vs},
            "h": eikonal["h"],
            "xlim": xlim,
            "ylim": ylim,
            "zlim": zlim,
        },
        "min_picks_per_eq": filtering["min_picks_per_eq"],
        "min_p_picks_per_eq": filtering["min_p_picks_per_eq"],
        "min_s_picks_per_eq": filtering["min_s_picks_per_eq"],
        "max_sigma11": filtering["max_sigma11"],
        "max_sigma22": filtering["max_sigma22"],
        "max_sigma12": filtering["max_sigma12"],
    }
    return gamma_config
