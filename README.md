# Seismic Workflow

This repository can be used in two ways:

1. Run the seismic processing workflow from the command line.
2. Import `seismic_workflow/` from Python code when developing new tools, notebooks, or tests.

If you are only using the workflow, start with the command-line section. You do not need to import Python modules manually.

## Quickstart

Create or update the Conda environment, activate it, inspect the CLI, then run the workflow:

```bash
conda env update -f environment.yml
conda activate catalog
python main.py --help
python main.py --config config.yaml
```

After installing the package, the same CLI is available as:

```bash
seismic-workflow --config config.yaml
```

The user-editable settings are in [config.yaml](./config.yaml).

## Main CLI Commands

`main.py` is the main entrypoint. It decides which workflow stages to run.

| Command | What it does |
| --- | --- |
| `python main.py` | Run the full workflow. |
| `python -m seismic_workflow.main` | Run the full workflow through the package module. |
| `seismic-workflow` | Run the installed PyPI-style entrypoint. |
| `python main.py --config config.yaml` | Run the full workflow with an explicit config file. |
| `python main.py continue` | Continue from the HypoEllipse output check, stages `06` to `08`. |
| `python main.py 03` | Run one stage by ID. |
| `python main.py --from 03` | Run from stage `03` through the end. |
| `python main.py --only 06 07` | Run only the selected stage IDs. |
| `python main.py gamma-analysis` | Run optional GaMMA picking/association analysis. |
| `python main.py plot-catalog` | Run optional catalog plotting. |
| `python main.py threshold-analysis` | Run optional threshold comparison plots. |
| `python main.py cc-dd-test` | Run optional cross-correlation differential-time test. |

## Single Stage Commands

The easiest way to run one stage is through `main.py`:

```bash
python main.py 03
```

Optional launchers are available inside the package:

```bash
python -m seismic_workflow.optional.plot_catalog
python -m seismic_workflow.optional.cc_dd_non_testato
python -m seismic_workflow.optional.analyse_thr_results
```

## Repository Layout

| Path | Purpose |
| --- | --- |
| `main.py` | Compatibility wrapper for the package CLI. |
| `config.yaml` | User settings only. No calculations happen here. |
| `environment.yml` | Conda environment definition. |
| `seismic_workflow/` | Importable workflow implementation. |
| `tests/` | Smoke tests for runtime context and derived settings. |

## Using The Python Library

The `seismic_workflow/` package exists so Python code can reuse workflow stages without copying script logic.

Run a single stage from Python:

```python
from seismic_workflow.context import build_context
from seismic_workflow.phase_picking import run_phase_picking

ctx = build_context("config.yaml")
run_phase_picking(ctx)
```

Run another stage:

```python
from seismic_workflow.context import build_context
from seismic_workflow.association import run_association

ctx = build_context("config.yaml")
run_association(ctx)
```

This is useful for notebooks, tests, new scripts, or a future interface around the same processing code.

## Inside `seismic_workflow/`

| Module | Purpose |
| --- | --- |
| `main.py` | Main CLI orchestrator for the whole workflow. |
| `optional/` | Optional launchers for plotting, threshold analysis, GaMMA analysis, and cross-correlation DD tests. |
| `context.py` | Loads `config.yaml`, validates settings, builds derived paths/settings, and lazily creates heavy objects such as models, devices, transformers, and FDSN clients. |
| `download.py` | Implementation for waveform/station download. |
| `data_cleaning.py` | Implementation for the cleaning stage. |
| `phase_picking.py` | Implementation for CNN phase picking and pick aggregation. |
| `association.py` | Implementation for GaMMA association and raw catalog generation. |
| `absolute_location_prep.py` | Implementation for HypoEllipse/Hypo71 preparation files. |
| `hypoellipse_check.py` | Runs HypoEllipse with Docker using generated input files. |
| `location_filtering.py` | Parses HypoEllipse output and filters location results. |
| `relative_relocation.py` | Generates HypoDD input files. |
| `analysis.py` | Optional GaMMA result analysis. |
| `plotting.py` | Optional catalog plotting. |
| `threshold_analysis.py` | Optional threshold comparison analysis. |
| `cc_dd_test.py` | Optional experimental cross-correlation DD logic. |

## Understanding `config.yaml`

`config.yaml` contains explicit user settings only. It should not calculate paths, create folders, connect to services, or load models. Those runtime values are built by `seismic_workflow.context`.

| Section | Controls |
| --- | --- |
| `case_study` | Case name, optional external output folder, and whether to run downloads. |
| `geography` | Latitude/longitude bounds for download and association. |
| `dates` | Start/end date and year. |
| `stations` | Network, channel, station filters, and FDSN providers. |
| `model` | Neural-network choice, pretrained/custom model options, batch size, and pick thresholds. |
| `gamma` | GaMMA association bounds, velocity settings, DBSCAN, eikonal, and filtering parameters. |
| `analysis` | Analysis log filename. |
| `plotting` | GMT/PyGMT plotting settings. |
| `hypoellipse` | Minimum P/S picks for HypoEllipse preparation, plus velocity model and parameter file paths. |
| `dd` | Filters for differential relocation input generation. |
| `script11` | Parameters for the experimental cross-correlation DD script. |
| `script12` | Threshold map for threshold comparison analysis. |

## Mental Model

- `python main.py` runs the full workflow controller.
- `python main.py 03` runs one stage by ID.
- `python -m seismic_workflow.main` runs the same controller through the package.
- `python -m seismic_workflow.optional.plot_catalog` runs an optional package launcher.
- `import seismic_workflow.phase_picking` reuses the implementation from Python code.

Most users only need `main.py` and `config.yaml`.
