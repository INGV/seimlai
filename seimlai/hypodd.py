#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Compile and run ph2dt and hypoDD with dataset-sized Fortran include files.
"""

from hashlib import sha256
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

PHASE_INPUT_NAME = "phase.dat"
STATION_INPUT_NAME = "station.dat"
DTCC_NAME = "dt.cc"
DTCT_NAME = "dt.ct"
EVENT_DAT_NAME = "event.dat"
EVENT_SEL_NAME = "event.sel"
STATION_SEL_NAME = "station.sel"
PH2DT_INPUT_NAME = "ph2dt.inp"
HYPODD_INPUT_NAME = "hypoDD.inp"
PH2DT_INCLUDE_NAME = "ph2dt.inc"
HYPODD_INCLUDE_NAME = "hypoDD.inc"
HYPODD_RELOC_NAME = "hypoDD.reloc"
HYPODD_SOURCE_REF = "V2.1b"
HYPODD_CONFIGURATION_DIR = Path(__file__).resolve().parent.parent / "user_configuration" / "hypodd"
HYPODD_DOCKERFILE = HYPODD_CONFIGURATION_DIR / "Dockerfile"
PH2DT_TEMPLATE = HYPODD_CONFIGURATION_DIR / PH2DT_INCLUDE_NAME
HYPODD_TEMPLATE = HYPODD_CONFIGURATION_DIR / HYPODD_INCLUDE_NAME
HYPODD_RELOC_HEADER = "# ID LAT LON DEPTH X Y Z EX EY EZ YEAR MONTH DAY HOUR MIN SEC MAG NCCP NCCS NCTP NCTS RCC RCT CID"


def _require_file(path, label, allow_empty=False):
    path = Path(path)
    if not path.exists():
        print(f"ERROR: {label} not found: {path}")
        sys.exit(1)
    if not allow_empty and path.stat().st_size == 0:
        print(f"ERROR: {label} is empty: {path}")
        sys.exit(1)


def _docker_is_ready():
    return subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def _ensure_docker_ready(timeout_seconds):
    if _docker_is_ready():
        return

    if platform.system() == "Darwin":
        print("Docker is not ready. Opening Docker Desktop...")
        subprocess.run(["open", "-a", "Docker"], check=False)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if _docker_is_ready():
                return
            time.sleep(3)

    print("ERROR: Docker is not running or is not reachable.")
    print("Start Docker Desktop and rerun this step.")
    sys.exit(1)


def _format_value(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _format_row(values):
    return " ".join(_format_value(value) for value in values)


def _write_ph2dt_input(path, cfg, station_name=STATION_INPUT_NAME, phase_name=PHASE_INPUT_NAME):
    params = [
        cfg["min_weight"],
        cfg["max_dist_km"],
        cfg["max_sep_km"],
        cfg["max_neighbors"],
        cfg["min_links"],
        cfg["min_observations"],
        cfg["max_observations"],
    ]
    path.write_text(
        "\n".join([
            "* ph2dt.inp - input control file for program ph2dt",
            "* Input station file:",
            station_name,
            "* Input phase file:",
            phase_name,
            "* MINWGHT MAXDIST MAXSEP MAXNGH MINLNK MINOBS MAXOBS",
            _format_row(params),
            "",
        ]),
        encoding="utf-8",
    )


def _model_rows(model_cfg):
    top = list(model_cfg["top_km"])
    vp = list(model_cfg["vp_km_s"])
    if len(top) != len(vp):
        raise ValueError("hypodd.velocity_model.top_km and vp_km_s must have the same length.")
    if not top:
        raise ValueError("hypodd.velocity_model must contain at least one layer.")

    ratio = model_cfg["vp_vs_ratio"]
    if isinstance(ratio, list):
        ratios = ratio
        if len(ratios) != len(top):
            raise ValueError("hypodd.velocity_model.vp_vs_ratio list must match top_km length.")
    else:
        ratios = [ratio] * len(top)

    return (
        _format_row([*top, -9]),
        _format_row([*vp, -9]),
        _format_row([*ratios, -9]),
    )


def _write_hypodd_input(path, cfg, output_prefix="../output"):
    relocation_cfg = cfg["relocation"]
    iteration_sets = relocation_cfg["iteration_sets"]
    if not iteration_sets:
        raise ValueError("hypodd.relocation.iteration_sets must contain at least one row.")
    for row in iteration_sets:
        if len(row) != 10:
            raise ValueError("each hypodd.relocation.iteration_sets row must have 10 values.")

    top_row, vp_row, ratio_row = _model_rows(cfg["velocity_model"])
    lines = [
        "hypoDD_2",
        "*--- input file selection",
        DTCC_NAME,
        DTCT_NAME,
        EVENT_SEL_NAME,
        STATION_SEL_NAME,
        "*--- output file selection",
        f"{output_prefix}/hypoDD.loc",
        f"{output_prefix}/{HYPODD_RELOC_NAME}",
        f"{output_prefix}/hypoDD.sta",
        f"{output_prefix}/hypoDD.res",
        f"{output_prefix}/hypoDD.src",
        "*--- data type selection: IDAT IPHA MAXDIST",
        _format_row([
            relocation_cfg["idat"],
            relocation_cfg["ipha"],
            relocation_cfg["max_dist_km"],
        ]),
        "*--- event clustering: OBSCC OBSCT MINDIST MAXDIST MAXGAP",
        _format_row([
            relocation_cfg["obscc"],
            relocation_cfg["obsct"],
            relocation_cfg["min_pair_station_dist"],
            relocation_cfg["max_pair_station_dist"],
            relocation_cfg["max_gap"],
        ]),
        "*--- solution control: ISTART ISOLV IAQ NSET",
        _format_row([
            relocation_cfg["istart"],
            relocation_cfg["isolve"],
            relocation_cfg["iaq"],
            len(iteration_sets),
        ]),
        "*--- data weighting: NITER WTCCP WTCCS WRCC WDCC WTCTP WTCTS WRCT WDCT DAMP",
    ]
    lines.extend(_format_row(row) for row in iteration_sets)
    lines.extend([
        "*--- 1D local model with variable vp/vs ratio",
        "1",
        top_row,
        vp_row,
        ratio_row,
        "*--- event selection: CID, then optional event IDs",
        _format_value(relocation_cfg["cluster_id"]),
        "* ID",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _dimension_with_headroom(count):
    if count < 0:
        raise ValueError("dimension counts cannot be negative.")
    ten_percent_headroom = (count * 110 + 99) // 100
    return max(count + 1, ten_percent_headroom)


def _count_nonempty_lines(path):
    return sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())


def _phase_file_counts(path):
    event_count = 0
    current_phases = 0
    max_phases = 0
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if event_count:
                max_phases = max(max_phases, current_phases)
            event_count += 1
            current_phases = 0
        else:
            if event_count == 0:
                raise ValueError(f"phase.dat contains a phase before its first event header at line {line_number}.")
            current_phases += 1
    max_phases = max(max_phases, current_phases)
    if event_count == 0:
        raise ValueError("phase.dat contains no event headers.")
    if max_phases == 0:
        raise ValueError("phase.dat contains no phase observations.")
    return event_count, max_phases


def _count_observations(path):
    return sum(
        1
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"hypodd.dimensions.{name} must be a positive integer.")
    return value


def _validate_dimension_config(cfg):
    dimensions = cfg["dimensions"]
    mode = str(dimensions["mode"]).lower()
    if mode not in {"auto", "manual"}:
        raise ValueError("hypodd.dimensions.mode must be 'auto' or 'manual'.")
    for key in ("maxeve0", "maxlay", "maxcl"):
        _positive_int(dimensions[key], key)

    layer_count = len(cfg["velocity_model"]["top_km"])
    if mode == "auto" and dimensions["maxlay"] < layer_count:
        raise ValueError(
            f"hypodd.dimensions.maxlay is {dimensions['maxlay']}, but the configured velocity model has {layer_count} layers."
        )

    idat = cfg["relocation"]["idat"]
    isolve = cfg["relocation"]["isolve"]
    if idat not in {0, 1, 2, 3}:
        raise ValueError("hypodd.relocation.idat must be 0, 1, 2, or 3.")
    if isolve not in {1, 2}:
        raise ValueError("hypodd.relocation.isolve must be 1 (SVD) or 2 (LSQR).")
    return mode


def _set_parameter_block(lines, name, active):
    begin = f"c BEGIN {name} PARAMETERS"
    end = f"c END {name} PARAMETERS"
    if lines.count(begin) != 1 or lines.count(end) != 1:
        raise ValueError(f"include template must contain exactly one {name} parameter block.")
    start = lines.index(begin)
    stop = lines.index(end)
    if stop <= start:
        raise ValueError(f"include template has an invalid {name} parameter block.")

    for index in range(start + 1, stop):
        line = lines[index]
        is_comment = bool(line) and line[0] in "cC*!"
        if active and is_comment:
            lines[index] = line[1:]
        elif not active and line and not is_comment:
            lines[index] = "c" + line


def _active_parameter_values(content, expected_names):
    active_lines = [
        line for line in content.splitlines()
        if line and line[0] not in "cC*!"
    ]
    parameter_lines = [
        line for line in active_lines
        if re.match(r"^\s*parameter\s*\(", line, flags=re.IGNORECASE)
    ]
    if len(parameter_lines) != 1:
        raise ValueError("rendered include file must contain exactly one active parameter block.")

    active_content = "\n".join(active_lines)
    if "{{" in active_content or "}}" in active_content:
        raise ValueError("rendered include file contains an unresolved automatic value.")

    values = {}
    for name in expected_names:
        matches = re.findall(rf"\b{re.escape(name)}\s*=\s*([+-]?\d+)", active_content, flags=re.IGNORECASE)
        if len(matches) != 1:
            raise ValueError(f"rendered include file must define {name} exactly once.")
        values[name] = int(matches[0])
        if values[name] <= 0:
            raise ValueError(f"rendered include parameter {name} must be positive.")
    return values


def _render_include(template_path, output_path, mode, automatic_values, expected_names):
    lines = Path(template_path).read_text(encoding="utf-8").splitlines()
    _set_parameter_block(lines, "AUTO", mode == "auto")
    _set_parameter_block(lines, "MANUAL", mode == "manual")
    content = "\n".join(lines) + "\n"
    if mode == "auto":
        for name, value in automatic_values.items():
            token = "{{" + name + "}}"
            if content.count(token) != 1:
                raise ValueError(f"include template must contain automatic token {token} exactly once.")
            content = content.replace(token, str(value))

    values = _active_parameter_values(content, expected_names)
    Path(output_path).write_text(content, encoding="utf-8")
    return values


def _validate_minimums(values, minimums, include_name):
    for name, minimum in minimums.items():
        if values[name] < minimum:
            raise ValueError(
                f"manual {include_name} parameter {name} is {values[name]}, but the input requires at least {minimum}."
            )


def _ph2dt_dimensions(phase_path, station_path):
    events, max_phases = _phase_file_counts(phase_path)
    stations = _count_nonempty_lines(station_path)
    if stations == 0:
        raise ValueError("station.dat contains no stations.")
    return {
        "MEV": _dimension_with_headroom(events),
        "MSTA": _dimension_with_headroom(stations),
        "MOBS": _dimension_with_headroom(max_phases),
    }, {
        "MEV": events + 1,
        "MSTA": stations + 1,
        "MOBS": max_phases + 1,
    }


def _hypodd_dimensions(run_dir, cfg):
    event_count = _count_nonempty_lines(run_dir / EVENT_SEL_NAME)
    station_count = _count_nonempty_lines(run_dir / STATION_SEL_NAME)
    if event_count == 0:
        raise ValueError("event.sel contains no selected events.")
    if station_count == 0:
        raise ValueError("station.sel contains no selected stations.")

    idat = cfg["relocation"]["idat"]
    observation_count = 0
    if idat in {1, 3}:
        observation_count += _count_observations(run_dir / DTCC_NAME)
    if idat in {2, 3}:
        observation_count += _count_observations(run_dir / DTCT_NAME)

    maxdata = _dimension_with_headroom(observation_count)
    dimensions_cfg = cfg["dimensions"]
    values = {
        "MAXEVE": _dimension_with_headroom(event_count),
        "MAXDATA": maxdata,
        "MAXEVE0": dimensions_cfg["maxeve0"],
        "MAXDATA0": maxdata + 4 if cfg["relocation"]["isolve"] == 1 else 1,
        "MAXLAY": dimensions_cfg["maxlay"],
        "MAXSTA": _dimension_with_headroom(station_count),
        "MAXCL": dimensions_cfg["maxcl"],
    }
    minimums = {
        "MAXEVE": event_count + 1,
        "MAXDATA": observation_count + 1,
        "MAXEVE0": 1,
        "MAXDATA0": observation_count + 4 if cfg["relocation"]["isolve"] == 1 else 1,
        "MAXLAY": len(cfg["velocity_model"]["top_km"]),
        "MAXSTA": station_count + 1,
        "MAXCL": 1,
    }
    return values, minimums


def _derived_image_name(base_image, program, include_content):
    if "@" in base_image:
        raise ValueError("hypodd.docker_image must be a name or tag, not a digest reference.")
    slash_index = base_image.rfind("/")
    colon_index = base_image.rfind(":")
    if colon_index > slash_index:
        repository = base_image[:colon_index]
        base_tag = base_image[colon_index + 1:]
    else:
        repository = base_image
        base_tag = "latest"
    if not repository or not base_tag:
        raise ValueError("hypodd.docker_image is not a valid Docker image name.")

    dockerfile_content = HYPODD_DOCKERFILE.read_bytes()
    digest = sha256(
        HYPODD_SOURCE_REF.encode("utf-8")
        + b"\0"
        + program.encode("utf-8")
        + b"\0"
        + include_content.encode("utf-8")
        + b"\0"
        + dockerfile_content
    ).hexdigest()[:12]
    return f"{repository}:{base_tag}-{program.lower()}-{digest}"


def _ensure_docker_image(image, target, program, run_dir, log_dir):
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode == 0:
        print(f"Using cached Docker image: {image}")
        return

    log_path = Path(log_dir) / f"docker-build-{program}.log"
    print(f"Docker image not found locally: {image}")
    print(f"Building {program} with the rendered include file...")
    with log_path.open("w", encoding="utf-8") as log_file:
        build = subprocess.run(
            [
                "docker", "build",
                "--build-arg", f"HYPODD_REF={HYPODD_SOURCE_REF}",
                "--target", target,
                "-t", image,
                "-f", str(HYPODD_DOCKERFILE),
                str(Path(run_dir).resolve()),
            ],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    if build.returncode != 0:
        raise RuntimeError(f"Docker image build failed for {image}. See {log_path}.")


def _run_docker_command(image, hypodd_dir, work_dir, log_dir, binary, input_name):
    stdout_path = Path(log_dir) / f"{binary}.stdout"
    stderr_path = Path(log_dir) / f"{binary}.stderr"
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{Path(hypodd_dir).resolve()}:/work",
        "-w",
        f"/work/{Path(work_dir).resolve().relative_to(Path(hypodd_dir).resolve()).as_posix()}",
        image,
        binary,
        input_name,
    ]

    print(f"Running {binary} in Docker image {image}")
    with stdout_path.open("w", encoding="utf-8") as stdout_file:
        result = subprocess.run(
            command,
            stdout=stdout_file,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    stderr_path.write_text(result.stderr or "", encoding="utf-8")

    if result.returncode != 0:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        stdout_tail = stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
        if stdout_tail:
            print("\n".join(stdout_tail), file=sys.stderr)
        raise RuntimeError(f"{binary} failed with exit code {result.returncode}. See logs in {log_dir}.")

    dimension_errors = [
        line.strip()
        for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines()
        if "increase" in line.lower() and ".inc" in line.lower()
    ]
    if dimension_errors:
        raise RuntimeError(f"{binary} reported an undersized include parameter: {dimension_errors[-1]}")


def _add_reloc_header(path):
    path = Path(path)
    content = path.read_text(encoding="utf-8")
    if content.startswith(HYPODD_RELOC_HEADER):
        return
    path.write_text(f"{HYPODD_RELOC_HEADER}\n{content}", encoding="utf-8")


def _prepare_run_dirs(ctx):
    ph2dt_input_dir = Path(ctx.paths.hypodd_ph2dt_input_path).parent
    ph2dt_output_dir = Path(ctx.paths.hypodd_run_dir)
    hypodd_input_dir = Path(ctx.paths.hypodd_input_dir)
    output_dir = Path(ctx.paths.hypodd_output_dir)
    ph2dt_input_dir.mkdir(parents=True, exist_ok=True)
    ph2dt_output_dir.mkdir(parents=True, exist_ok=True)
    hypodd_input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    phase_path = Path(ctx.paths.dd_output_file)
    station_path = Path(ctx.paths.dd_station_file)
    dtcc_path = Path(ctx.paths.dd_dtcc_file)

    _require_file(phase_path, "HypoDD phase/catalog input")
    _require_file(station_path, "HypoDD station input")
    _require_file(dtcc_path, "cross-correlation differential-time input", allow_empty=True)
    _require_file(PH2DT_TEMPLATE, "local ph2dt include template")
    _require_file(HYPODD_TEMPLATE, "local hypoDD include template")
    _require_file(HYPODD_DOCKERFILE, "local HypoDD Dockerfile")

    return ph2dt_input_dir, ph2dt_output_dir, hypodd_input_dir


def _run(ctx):
    cfg = ctx.raw.hypodd
    mode = _validate_dimension_config(cfg)
    _model_rows(cfg["velocity_model"])
    ph2dt_input_dir, ph2dt_output_dir, hypodd_input_dir = _prepare_run_dirs(ctx)
    hypodd_dir = Path(ctx.paths.hypodd_dir)
    output_dir = Path(ctx.paths.hypodd_output_dir)
    phase_path = Path(ctx.paths.dd_output_file)
    station_path = Path(ctx.paths.dd_station_file)

    _write_ph2dt_input(
        ph2dt_input_dir / PH2DT_INPUT_NAME,
        cfg["ph2dt"],
        f"../input/{station_path.name}",
        f"../input/{phase_path.name}",
    )
    _write_hypodd_input(hypodd_input_dir / HYPODD_INPUT_NAME, cfg)
    _ensure_docker_ready(cfg["docker_start_timeout_seconds"])

    ph2dt_auto, ph2dt_minimums = _ph2dt_dimensions(
        phase_path,
        station_path,
    )
    with tempfile.TemporaryDirectory(prefix="seimlai-hypodd-") as build_dir_name:
        build_dir = Path(build_dir_name)
        ph2dt_values = _render_include(
            PH2DT_TEMPLATE,
            build_dir / PH2DT_INCLUDE_NAME,
            mode,
            ph2dt_auto,
            ("MEV", "MSTA", "MOBS"),
        )
        if mode == "manual":
            _validate_minimums(ph2dt_values, ph2dt_minimums, PH2DT_INCLUDE_NAME)
        print("ph2dt dimensions: " + ", ".join(f"{key}={value}" for key, value in ph2dt_values.items()))

        ph2dt_content = (build_dir / PH2DT_INCLUDE_NAME).read_text(encoding="utf-8")
        ph2dt_image = _derived_image_name(cfg["docker_image"], "ph2dt", ph2dt_content)
        _ensure_docker_image(ph2dt_image, "ph2dt-runtime", "ph2dt", build_dir, output_dir)
        _run_docker_command(
            ph2dt_image,
            hypodd_dir,
            ph2dt_output_dir,
            output_dir,
            "ph2dt",
            f"../input/{PH2DT_INPUT_NAME}",
        )
        for name in (DTCT_NAME, EVENT_DAT_NAME, EVENT_SEL_NAME, STATION_SEL_NAME):
            _require_file(ph2dt_output_dir / name, f"ph2dt output {name}")
        for name in (DTCT_NAME, EVENT_SEL_NAME, STATION_SEL_NAME):
            shutil.copy2(ph2dt_output_dir / name, hypodd_input_dir / name)

        hypodd_auto, hypodd_minimums = _hypodd_dimensions(hypodd_input_dir, cfg)
        hypodd_values = _render_include(
            HYPODD_TEMPLATE,
            build_dir / HYPODD_INCLUDE_NAME,
            mode,
            hypodd_auto,
            ("MAXEVE", "MAXDATA", "MAXEVE0", "MAXDATA0", "MAXLAY", "MAXSTA", "MAXCL"),
        )
        if mode == "manual":
            _validate_minimums(hypodd_values, hypodd_minimums, HYPODD_INCLUDE_NAME)
        print("hypoDD dimensions: " + ", ".join(f"{key}={value}" for key, value in hypodd_values.items()))

        hypodd_content = (build_dir / HYPODD_INCLUDE_NAME).read_text(encoding="utf-8")
        hypodd_image = _derived_image_name(cfg["docker_image"], "hypodd", hypodd_content)
        _ensure_docker_image(hypodd_image, "hypodd-runtime", "hypoDD", build_dir, output_dir)
        _run_docker_command(
            hypodd_image,
            hypodd_dir,
            hypodd_input_dir,
            output_dir,
            "hypoDD",
            HYPODD_INPUT_NAME,
        )
    reloc_path = Path(ctx.paths.hypodd_reloc_path)
    _require_file(reloc_path, "HypoDD relocation output")
    _add_reloc_header(reloc_path)
    print(f"HypoDD relocation written to: {reloc_path}")


def run(ctx):
    try:
        _run(ctx)
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


def main():
    from seimlai.context import build_context

    run(build_context("user_configuration/config.yaml"))


run_hypodd = run


if __name__ == "__main__":
    main()
