from seismic_workflow.context import build_context, ensure_initial_directories


def build_optional_context(config_path: str = "config.yaml"):
    ctx = build_context(config_path)
    ensure_initial_directories(ctx)
    return ctx
