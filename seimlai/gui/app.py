"""Main application module for SeiMLAI GUI.

Builds the NiceGUI layout with top navigation bar, sidebar drawer, and dynamic
pages for configuration, pipeline execution, interactive mapping, and log viewing.
"""

from __future__ import annotations

from pathlib import Path
from nicegui import app, ui

from seimlai.gui.pages.config_editor import create_config_editor
from seimlai.gui.pages.pipeline_runner import create_pipeline_runner
from seimlai.gui.pages.live_map import create_live_map
from seimlai.gui.components.log_viewer import LogViewer
from seimlai.gui.services.config_service import ConfigService
from seimlai.gui.services.pipeline_service import PipelineService
from seimlai.gui.services.catalog_watcher import CatalogWatcher


# Session-wide service instances
_SERVICES: dict = {}


def _get_services(config_path: str):
    """Retrieve or initialize singleton services."""
    if "config" not in _SERVICES or _SERVICES["config"].config_path != Path(config_path):
        config_svc = ConfigService(config_path)
        pipeline_svc = PipelineService()
        catalog_watcher = CatalogWatcher(config_path)
        catalog_watcher.start_watching(poll_interval_seconds=2.0)

        _SERVICES["config"] = config_svc
        _SERVICES["pipeline"] = pipeline_svc
        _SERVICES["watcher"] = catalog_watcher

    return _SERVICES["config"], _SERVICES["pipeline"], _SERVICES["watcher"]


def build_main_ui(config_path: str = "user_configuration/config.yaml") -> None:
    """Build the complete SeiMLAI UI view."""
    config_svc, pipeline_svc, catalog_watcher = _get_services(config_path)
    dark_mode = ui.dark_mode(app.storage.user.get("dark_mode", False)).bind_value(app.storage.user, "dark_mode")

    # Top Header
    with ui.header().classes("seimlai-header"):
        with ui.row().classes("seimlai-header-bar"):
            with ui.row().classes("seimlai-brand"):
                ui.element("img").props('src=/seimlai-assets/seimlai-logo.svg alt="SeiMLAI logo"').classes("seimlai-brand-mark")
                ui.label("SeiMLAI").classes("seimlai-brand-name")
                ui.label("High-resolution seismic catalog workflow").classes("seimlai-brand-description")
            ui.switch("Dark mode").bind_value(dark_mode).props("dense color=primary checked-icon=sym_o_dark_mode unchecked-icon=sym_o_light_mode").classes("seimlai-theme-toggle")

        # Main Navigation Tabs & View Containers
        with ui.tabs().props("dense inline-label no-caps align=left active-color=primary indicator-color=primary").classes("seimlai-nav") as nav_tabs:
            tab_runner = ui.tab("▶️ Pipeline Runner", label="Pipeline runner", icon="sym_o_play_circle")
            tab_cases = ui.tab("Case studies", icon="sym_o_folder_open")
            tab_config = ui.tab("⚙️ Configuration", label="Configuration", icon="sym_o_tune")
            tab_map = ui.tab("🗺️ Live Map", label="Live map", icon="sym_o_map")
            tab_logs = ui.tab("📋 Full Logs", label="Full logs", icon="sym_o_terminal")

    with ui.tab_panels(nav_tabs, value=tab_runner, animated=False).classes("seimlai-panels w-full p-0"):

        # 1. Pipeline Runner Page
        with ui.tab_panel(tab_runner).classes("p-5"):
            create_pipeline_runner(
                pipeline_svc,
                config_svc,
                on_navigate_config=lambda: nav_tabs.set_value(tab_config),
            )

        with ui.tab_panel(tab_cases).classes("p-5"):
            with ui.column().classes("w-full max-w-5xl gap-4"):
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-1"):
                        ui.label("Case studies").classes("seimlai-config-title")
                        ui.label("Folders in case_studies and the currently configured folder.").classes("text-sm text-slate-500")
                    ui.button("Refresh", icon="sym_o_refresh", on_click=lambda: show_cases.refresh()).props("outline dense color=secondary")

                @ui.refreshable
                def show_cases():
                    base = Path.cwd()
                    cases_dir = base / "case_studies"
                    cases_dir.mkdir(exist_ok=True)
                    configured = config_svc.get("case_study.personal_folder")
                    if configured:
                        configured_path = Path(configured)
                    else:
                        name = config_svc.get("case_study.name", "case_study")
                        new_path = cases_dir / name
                        old_path = base / name
                        configured_path = old_path if old_path.is_dir() and not new_path.exists() else new_path
                    paths = {p.resolve() for p in cases_dir.iterdir() if p.is_dir()}
                    paths.add(configured_path.resolve())

                    def select_case(path):
                        if pipeline_svc.is_running:
                            ui.notify("Stop the pipeline before switching case studies.", type="warning")
                            return
                        if config_svc.is_dirty or has_invalid_fields():
                            ui.notify("Save or discard configuration changes before switching case studies.", type="warning")
                            return
                        if not path.is_dir():
                            ui.notify("The selected folder no longer exists.", type="negative")
                            show_cases.refresh()
                            return
                        try:
                            config_svc.select_case(path)
                        except Exception as exc:
                            config_svc.reset_to_saved()
                            ui.notify(f"Could not select case study: {exc}", type="negative")
                            return
                        refresh_config_fields()
                        catalog_watcher.refresh()
                        show_cases.refresh()
                        ui.notify(f"Loaded case study: {path.name}", type="positive")

                    for path in sorted(paths, key=lambda p: str(p).casefold()):
                        with ui.card().classes("seimlai-config-section w-full"):
                            with ui.row().classes("w-full items-center justify-between"):
                                with ui.row().classes("items-center gap-3"):
                                    ui.icon("sym_o_folder").classes("text-xl text-primary")
                                    with ui.column().classes("gap-0"):
                                        ui.label(path.name).classes("font-semibold")
                                        ui.label(str(path)).classes("text-xs text-slate-500 font-mono")
                                if path == configured_path.resolve():
                                    ui.badge("Active", color="primary")
                                elif path.is_dir():
                                    ui.button("Load", icon="sym_o_folder_open", on_click=lambda p=path: select_case(p)).props("outline dense color=primary")
                            if not path.is_dir():
                                ui.label("Folder not found").classes("text-sm text-slate-500")
                show_cases()

        # 2. Config Editor Page
        with ui.tab_panel(tab_config).classes("p-5"):
            has_invalid_fields, refresh_config_fields = create_config_editor(config_svc)

        # 3. Live Map Page (Expanded near-full screen)
        with ui.tab_panel(tab_map).classes("p-2"):
            create_live_map(catalog_watcher, config_svc)

        # 4. Full-screen Log Terminal Page
        with ui.tab_panel(tab_logs).classes("p-5"):
            with ui.column().classes("seimlai-full-logs w-full"):
                with ui.column().classes("seimlai-full-logs-heading gap-1"):
                    ui.label("Full logs").classes("seimlai-full-logs-title")
                    ui.label("Search and follow the live execution output.").classes("text-sm text-slate-500")
                full_log_viewer = LogViewer(initial_logs=pipeline_svc.logs, height="100%")
                pipeline_svc.add_log_listener(lambda line: full_log_viewer.append(line))

    # Clean shutdown of background threads
    app.on_shutdown(lambda: catalog_watcher.stop_watching())


def launch_gui(
    config_path: str = "user_configuration/config.yaml",
    host: str = "127.0.0.1",
    port: int = 8080,
    native: bool = False,
    reload: bool = False,
) -> None:
    """Launch the SeiMLAI NiceGUI application web server."""
    static_dir = Path(__file__).with_name("static")
    app.add_static_files("/seimlai-assets", static_dir)
    for field in (ui.input, ui.number, ui.select, ui.textarea):
        field.default_props("outlined dense stack-label")
    ui.button.default_props("no-caps unelevated")

    # Explicitly register root page so NiceGUI doesn't fallback to re-running sys.argv[0]
    @ui.page("/")
    def index():
        ui.page_title("SeiMLAI - Seismic Machine Learning Workflow")
        ui.add_css(static_dir / "theme.css")
        ui.add_body_html('<script>document.body.classList.add("seimlai-theme");</script>')
        ui.colors(
            primary="var(--seimlai-primary)",
            secondary="var(--seimlai-text-secondary)",
            accent="var(--seimlai-primary)",
            dark="var(--seimlai-surface)",
            dark_page="var(--seimlai-bg)",
            positive="var(--seimlai-success)",
            negative="var(--seimlai-error)",
            warning="var(--seimlai-warning)",
            info="var(--seimlai-running)",
        )
        build_main_ui(config_path)

    # Silence Matomo analytics probes from institutional/browser extensions
    @app.get("/matomo.js")
    @app.get("/matomo.php")
    @app.post("/matomo.php")
    def _silence_matomo():
        from starlette.responses import Response
        return Response(content="/* matomo probe neutralized */", media_type="application/javascript", status_code=200)

    print(f"\n[SeiMLAI GUI] Starting interactive interface at http://{host}:{port}")
    ui.run(
        title="SeiMLAI GUI",
        favicon=static_dir / "seimlai-logo.svg",
        host=host,
        port=port,
        native=native,
        reload=False,
        show=True,
        storage_secret="seimlai_secret_key_session",
    )
