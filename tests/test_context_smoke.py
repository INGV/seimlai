from seismic_workflow.context import build_context, ensure_initial_directories


def test_context_matches_expected_derived_values():
    ctx = build_context("config.yaml")
    p_threshold = ctx.raw.model["p_threshold"]
    s_threshold = ctx.raw.model["s_threshold"]
    expected_thr = f"{int(p_threshold * 10):02d}-{int(s_threshold * 10):02d}"

    assert ctx.derived.start_day == 304
    assert ctx.derived.end_day == 304
    assert ctx.derived.thr == expected_thr
    assert str(ctx.paths.project_root).endswith("Amatrice_catalog_test")
    assert str(ctx.paths.output_picks_dir).endswith(f"output/output_picks_{p_threshold}")
    assert str(ctx.paths.output_dir).endswith(f"output/output_catalog_{p_threshold}")
    assert str(ctx.paths.location_1d_quality_path).endswith(f"DD/location-1D_{expected_thr}.quality")

    gamma_config = ctx.derived.gamma_config
    assert gamma_config["x(km)"] == (230, 620)
    assert gamma_config["y(km)"] == (4650, 4800)
    assert gamma_config["z(km)"] == (0, 60)
    assert gamma_config["vel"] == {"p": 7.0, "s": 4.0}
    assert gamma_config["oversample_factor"] == 4
    assert gamma_config["bfgs_bounds"] == ((229, 621), (4649, 4801), (0, 61), (None, None))


def test_ensure_initial_directories_creates_dd_folder(tmp_path):
    ctx = build_context("config.yaml")
    ctx.paths = ctx.paths.__class__(
        **{
            **ctx.paths.__dict__,
            "project_root": tmp_path / "case",
            "output_base": tmp_path / "case" / "output",
            "output_dir": tmp_path / "case" / "output" / f"output_catalog_{ctx.raw.model['p_threshold']}",
            "dd_dir": tmp_path / "case" / "output" / f"output_catalog_{ctx.raw.model['p_threshold']}" / "DD",
        }
    )

    ensure_initial_directories(ctx)

    assert ctx.paths.dd_dir.is_dir()
