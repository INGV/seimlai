"""Config service for SeiMLAI GUI.

Handles loading, saving, updating (dot-notation), and validating
the SeiMLAI YAML configuration.
"""

from __future__ import annotations

import copy
from pathlib import Path
import os
import tempfile
from typing import Any, Callable
import yaml

from seimlai.context import case_study_root, validate_config


def _update_yaml_values(source: str, data: dict[str, Any]) -> str:
    """Replace YAML values at their parsed locations, preserving surrounding comments."""
    root = yaml.compose(source, Loader=yaml.SafeLoader)
    edits = []

    def update(node, value):
        if isinstance(node, yaml.MappingNode) and isinstance(value, dict):
            existing = {key.value: item for key, item in node.value}
            if set(existing) != set(value):
                raise ValueError("Configuration keys differ from the commented YAML template")
            for key, item in value.items():
                update(existing[key], item)
            return
        if isinstance(node, yaml.SequenceNode) and isinstance(value, list) and len(node.value) == len(value):
            for child, item in zip(node.value, value):
                update(child, item)
            return
        end = node.end_mark.index
        if isinstance(node, yaml.SequenceNode) and node.value and not node.flow_style:
            end = node.value[-1].end_mark.index
            while end > node.start_mark.index and source[end - 1].isspace():
                end -= 1
        if isinstance(node, yaml.ScalarNode):
            old = yaml.safe_load(source[node.start_mark.index:end])
            if type(old) is type(value) and old == value:
                return
        original = source[node.start_mark.index:end]
        if not isinstance(node, yaml.ScalarNode) and "#" in original:
            raise ValueError("Cannot replace a YAML collection containing comments without losing them")
        rendered = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=100000).strip()
        if rendered.endswith("\n..."):
            rendered = rendered[:-4]
        edits.append((node.start_mark.index, end, rendered))

    update(root, data)
    for start, end, rendered in sorted(edits, reverse=True):
        source = source[:start] + rendered + source[end:]
    if yaml.safe_load(source) != data:
        raise ValueError("Could not preserve YAML comments while saving configuration")
    return source


def _write_yaml_atomic(dest: Path, contents: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=dest.parent, delete=False) as f:
        temp_path = Path(f.name)
        try:
            f.write(contents)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp_path, dest)
    finally:
        temp_path.unlink(missing_ok=True)


class ConfigService:
    """Service to manage reading, editing, validating and persisting config.yaml."""

    def __init__(self, config_path: str | Path = "user_configuration/config.yaml"):
        self.config_path = Path(config_path)
        self._raw_data: dict[str, Any] = {}
        self._original_data: dict[str, Any] = {}
        self._dirty_keys: set[str] = set()
        self._change_callbacks: list[Callable[[str, Any], None]] = []

        if self.config_path.exists():
            self.load()
        else:
            self._raw_data = self.get_defaults()
            self._original_data = copy.deepcopy(self._raw_data)

    def load(self, path: str | Path | None = None) -> dict[str, Any]:
        """Load configuration from the specified or default file path."""
        target_path = Path(path) if path else self.config_path
        with open(target_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"File {target_path} is not a valid YAML mapping.")

        validate_config(data)
        self.config_path = target_path
        self._raw_data = copy.deepcopy(data)
        self._original_data = copy.deepcopy(data)
        self._dirty_keys.clear()
        return self._raw_data

    @property
    def data(self) -> dict[str, Any]:
        """Return the current in-memory configuration dictionary."""
        return self._raw_data

    @property
    def is_dirty(self) -> bool:
        """Return True if any field has been modified since last load/save."""
        return len(self._dirty_keys) > 0

    @property
    def dirty_keys(self) -> set[str]:
        """Return set of modified dot-notation keys."""
        return set(self._dirty_keys)

    def get(self, dot_key: str, default: Any = None) -> Any:
        """Get a value by dot-notation path, e.g. 'geography.minlatitude'."""
        keys = dot_key.split(".")
        curr = self._raw_data
        for k in keys:
            if not isinstance(curr, dict) or k not in curr:
                return default
            curr = curr[k]
        return curr

    def set(self, dot_key: str, value: Any) -> None:
        """Set a value by dot-notation path and mark as dirty if changed."""
        keys = dot_key.split(".")
        curr = self._raw_data
        for k in keys[:-1]:
            if k not in curr or not isinstance(curr[k], dict):
                curr[k] = {}
            curr = curr[k]

        old_val = curr.get(keys[-1])
        if old_val != value:
            curr[keys[-1]] = value
            original = self._original_data
            for key in keys:
                if not isinstance(original, dict) or key not in original:
                    original = object()
                    break
                original = original[key]
            if original == value:
                self._dirty_keys.discard(dot_key)
            else:
                self._dirty_keys.add(dot_key)
            self._notify_change(dot_key, value)

    def add_change_listener(self, callback: Callable[[str, Any], None]) -> None:
        """Register a callback for field updates: callback(dot_key, new_value)."""
        self._change_callbacks.append(callback)

    def _notify_change(self, dot_key: str, value: Any) -> None:
        for cb in self._change_callbacks:
            try:
                cb(dot_key, value)
            except Exception:
                pass

    def validate(self) -> list[str]:
        """Run validation and return a list of error strings (empty if valid)."""
        errors = []
        try:
            validate_config(self._raw_data)
        except Exception as e:
            errors.append(str(e))

        geo = self._raw_data.get("geography", {})
        minlat = geo.get("minlatitude")
        maxlat = geo.get("maxlatitude")
        minlon = geo.get("minlongitude")
        maxlon = geo.get("maxlongitude")

        if minlat is not None and maxlat is not None and minlat >= maxlat:
            errors.append(f"Geography error: minlatitude ({minlat}) must be strictly less than maxlatitude ({maxlat})")
        if minlon is not None and maxlon is not None and minlon >= maxlon:
            errors.append(f"Geography error: minlongitude ({minlon}) must be strictly less than maxlongitude ({maxlon})")

        model = self._raw_data.get("model", {})
        for thr_key in ("p_threshold", "s_threshold"):
            val = model.get(thr_key)
            if val is not None and not (0.0 <= float(val) <= 1.0):
                errors.append(f"Model error: {thr_key} ({val}) must be between 0.0 and 1.0")

        return errors

    def save(self, target_path: str | Path | None = None, *, _source: str | None = None) -> Path:
        """Validate and atomically save configuration while retaining YAML comments."""
        errors = self.validate()
        if errors:
            raise ValueError(f"Cannot save invalid configuration:\n" + "\n".join(errors))

        dest = Path(target_path) if target_path else self.config_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        template = dest.parent / "config.default.yaml"
        if _source is not None:
            source = _source
        elif dest.exists():
            source = dest.read_text(encoding="utf-8")
        elif template.exists():
            source = template.read_text(encoding="utf-8")
        else:
            source = yaml.safe_dump(self._raw_data, sort_keys=False, indent=2)
        if template.exists() and not any(line.lstrip().startswith("#") or " #" in line for line in source.splitlines()):
            source = template.read_text(encoding="utf-8")
        rendered = _update_yaml_values(source, self._raw_data)

        current_root = case_study_root(self._original_data["case_study"]).resolve()
        new_root = case_study_root(self._raw_data["case_study"]).resolve()
        snapshot = new_root / ".seimlai-config.yaml"
        if current_root != new_root and _source is None and snapshot.exists():
            raise ValueError("This case study has saved settings; use Load in Case studies.")
        if current_root != new_root and current_root.is_dir() and dest.exists():
            _write_yaml_atomic(current_root / ".seimlai-config.yaml", dest.read_text(encoding="utf-8"))
        previous_snapshot = snapshot.read_text(encoding="utf-8") if snapshot.exists() else None
        _write_yaml_atomic(snapshot, rendered)
        try:
            _write_yaml_atomic(dest, rendered)
        except Exception:
            if previous_snapshot is None:
                snapshot.unlink(missing_ok=True)
            else:
                _write_yaml_atomic(snapshot, previous_snapshot)
            raise

        self.config_path = dest
        self._original_data = copy.deepcopy(self._raw_data)
        self._dirty_keys.clear()
        return dest

    def select_case(self, path: Path) -> None:
        """Load the selected case's settings, or inherit the current saved settings."""
        if self.is_dirty:
            raise ValueError("Save or discard configuration changes before switching case studies.")
        path = path.resolve()
        snapshot = path / ".seimlai-config.yaml"
        source = snapshot.read_text(encoding="utf-8") if snapshot.exists() else None
        data = yaml.safe_load(source) if source is not None else copy.deepcopy(self._original_data)
        if not isinstance(data, dict):
            raise ValueError(f"File {snapshot} is not a valid YAML mapping.")
        validate_config(data)
        self._raw_data = copy.deepcopy(data)
        self._raw_data["case_study"]["name"] = path.name
        self._raw_data["case_study"]["personal_folder"] = str(path)
        try:
            if source is None:
                source = (self.config_path.read_text(encoding="utf-8") if self.config_path.exists()
                          else yaml.safe_dump(self._original_data, sort_keys=False))
            self.save(_source=source)
        except Exception:
            self.reset_to_saved()
            raise

    def reset_to_saved(self) -> None:
        """Revert in-memory changes back to the last loaded/saved state."""
        self._raw_data = copy.deepcopy(self._original_data)
        self._dirty_keys.clear()

    @staticmethod
    def get_defaults() -> dict[str, Any]:
        """Return a complete, valid default SeiMLAI configuration dictionary."""
        return {
            "case_study": {
                "name": "case_study",
                "personal_folder": None,
                "download_data": True,
            },
            "geography": {
                "minlatitude": 42.25,
                "maxlatitude": 43.12,
                "minlongitude": 11.75,
                "maxlongitude": 14.00,
            },
            "dates": {
                "starttime": "2016-10-30",
                "endtime": "2016-10-30",
            },
            "stations": {
                "network": "*",
                "channel": "BH?,HH?,EH?",
                "stations_list": "*",
                "fdsn_clients": ["IRIS", "INGV"],
            },
            "model": {
                "neural_network": "PhaseNet",
                "model_type": "original",
                "custom_model_path": None,
                "batch_size": 256,
                "p_threshold": 0.5,
                "s_threshold": 0.5,
            },
            "phase_picking": {
                "num_workers_cpu_mps": 2,
                "slurm_cpus_default": 4,
                "bandpass_freq_min": 0.5,
                "bandpass_freq_max": 30.0,
            },
            "gamma": {
                "dims": ["x(km)", "y(km)", "z(km)"],
                "use_dbscan": True,
                "use_amplitude": True,
                "x_km": [230, 620],
                "y_km": [4650, 4800],
                "z_km": [0, 60],
                "velocity": {"p": 7.0, "s": 4.0},
                "method": "BGMM",
                "dbscan_eps": 25,
                "dbscan_min_samples": 3,
                "eikonal": {
                    "z": [0.0, 5.5, 16.0, 32.0],
                    "p": [5.5, 5.5, 6.7, 7.8],
                    "vp_vs_ratio": 1.73,
                    "h": 1.0,
                },
                "filtering": {
                    "min_picks_per_eq": 6,
                    "min_p_picks_per_eq": 4,
                    "min_s_picks_per_eq": 3,
                    "max_sigma11": 1.5,
                    "max_sigma22": 1.0,
                    "max_sigma12": 1.0,
                },
            },
            "analysis": {
                "log_filename": "picking_analysis.log",
            },
            "plotting": {
                "gmt_library_path": "",
                "gmt_grid_path": "@earth_relief_15s",
                "region": [12.5, 14.00, 42.00, 43.50],
                "map_title": "Central Italy - Seismicity",
            },
            "hypoellipse": {
                "h71_min_p": 4,
                "h71_min_s": 2,
            },
            "hypoellipse_check": {
                "docker_image": "ingv/hypoellipse",
                "docker_start_timeout_seconds": 90,
            },
            "dd": {
                "max_gap": 180.0,
                "max_rms": 0.8,
                "max_erh": 2.0,
                "max_erz": 2.0,
            },
            "hypodd": {
                "docker_image": "hypodd:2.1b",
                "docker_start_timeout_seconds": 90,
                "dimensions": {
                    "mode": "auto",
                    "maxeve0": 1,
                    "maxlay": 14,
                    "maxcl": 30,
                },
                "ph2dt": {
                    "min_weight": 0.0,
                    "max_dist_km": 150.0,
                    "max_sep_km": 10.0,
                    "max_neighbors": 30,
                    "min_links": 8,
                    "min_observations": 8,
                    "max_observations": 30,
                },
                "relocation": {
                    "idat": 3,
                    "ipha": 3,
                    "max_dist_km": 50.0,
                    "obscc": 3,
                    "obsct": 13,
                    "min_pair_station_dist": -999,
                    "max_pair_station_dist": -999,
                    "max_gap": -999,
                    "istart": 2,
                    "isolve": 2,
                    "iaq": 1,
                    "cluster_id": 0,
                    "iteration_sets": [
                        [7, 0.2, 0.2, 10, 10, 1.0, 0.7, 10, 10, 120],
                        [5, 1.0, 0.7, 9, 8, 1.0, 0.7, 8, 6, 180],
                        [5, 1.0, 0.7, 8, 6, 0.1, 0.1, 8, 6, 200],
                        [5, 1.0, 0.7, 6, 4, 0.01, 0.01, 6, 4, 220],
                    ],
                },
                "velocity_model": {
                    "top_km": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 14.0, 16.0],
                    "vp_km_s": [5.0, 5.15, 5.30, 5.45, 5.60, 5.75, 5.90, 6.05, 6.20, 6.35, 6.50, 6.65, 6.80, 7.0],
                    "vp_vs_ratio": 1.86,
                },
            },
            "cc_dd": {
                "use_gpu": True,
                "gpu_batch_size": "auto",
                "max_dist_km_cc": 3.0,
                "min_common_picks_per_pair": 8,
                "min_readings_per_pair": 4,
                "cc_threshold": 0.8,
                "snr_threshold": 1.0,
                "max_abs_dt_seconds": 2.0,
                "p_win_before": 0.2,
                "p_win_after": 1.0,
                "p_max_lag": 0.3,
                "s_win_before": 0.5,
                "s_win_after": 1.5,
                "s_max_lag": 0.5,
                "freq_min": 2.0,
                "freq_max": 15.0,
                "filter_pad_seconds": 1.0,
                "p_channel": "??Z",
                "s_e_channel": "??E",
                "s_n_channel": "??N",
                "require_both_s_components": True,
                "peak_edge_margin_seconds": 0.01,
                "s_shift_tolerance_seconds": 0.02,
                "network": "*",
                "worker_count": None,
                "chunk_size": None,
            },
            "threshold_analysis": {
                "dpi": 300,
                "thresholds_map": {
                    "01-01": 0.1,
                    "02-02": 0.2,
                    "03-03": 0.3,
                    "04-04": 0.4,
                    "05-05": 0.5,
                    "06-06": 0.6,
                    "07-07": 0.7,
                    "08-08": 0.8,
                    "09-09": 0.9,
                },
            },
        }

