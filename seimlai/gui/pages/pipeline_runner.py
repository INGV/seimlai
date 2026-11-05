"""Pipeline Runner page for SeiMLAI GUI.

Allows executing the entire seismic workflow or selective steps, monitoring
per-step progress bars and status, and viewing live logs in a dedicated console.
"""

from __future__ import annotations

from nicegui import ui
from seimlai.gui.components.step_progress import StepProgressCard
from seimlai.gui.components.log_viewer import LogViewer
from seimlai.gui.services.config_service import ConfigService
from seimlai.gui.services.pipeline_service import PipelineService, StepState


def create_pipeline_runner(
    pipeline_svc: PipelineService,
    config_svc: ConfigService,
    on_navigate_config=None,
) -> None:
    """Render the pipeline execution view."""

    with ui.column().classes("seimlai-runner w-full gap-4"):
        # Top Control Card
        with ui.column().classes("seimlai-runner-controls w-full gap-4"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.row().classes("items-center gap-3"):
                    status_icon = ui.icon("sym_o_play_circle").classes("seimlai-runner-status text-gray-500")
                    with ui.column().classes("gap-0"):
                        ui.label("Pipeline runner").classes("seimlai-runner-title")
                        overall_status_label = ui.label("Ready to run stages 01–05").classes("text-sm text-gray-500")

                # Action buttons
                with ui.row().classes("items-center gap-2"):
                    run_all_btn = ui.button(
                        "Run full workflow",
                        icon="sym_o_play_arrow",
                        color="primary",
                    ).props("unelevated")

                    continue_btn = ui.button(
                        "Continue (04-05)",
                        icon="sym_o_fast_forward",
                        color="secondary",
                    ).props("outline")

                    stop_btn = ui.button(
                        "Stop",
                        icon="sym_o_stop",
                        color="negative",
                    ).props("outline").classes("hidden")

            # Secondary controls (selective execution)
            with ui.row().classes("seimlai-runner-toolbar w-full items-center justify-between text-xs"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("Step").classes("font-semibold text-gray-600")
                    step_select = ui.select(
                        {
                            "01": "01 - Download",
                            "02": "02 - Phase Picking (CNN)",
                            "03": "03 - Association (GaMMA)",
                            "04": "04 - Absolute Location",
                            "05": "05 - Relative Relocation",
                        },
                        value="01",
                    ).props("dense outlined").classes("w-60")

                    run_single_btn = ui.button("Run selected", icon="sym_o_play_circle").props("dense outline color=secondary")
                    run_from_btn = ui.button("Run from here", icon="sym_o_trending_flat").props("dense outline color=secondary")

                with ui.row().classes("items-center gap-2"):
                    ui.label("Utility").classes("font-semibold text-gray-600")
                    opt_select = ui.select(
                        {
                            "plot-catalog": "Plot Catalog (PyGMT)",
                            "gamma-analysis": "GaMMA Analysis",
                            "plot-hypoellipse": "Plot HypoEllipse",
                            "threshold-analysis": "Threshold Analysis",
                        },
                        value="plot-catalog",
                    ).props("dense outlined").classes("w-52")
                    run_opt_btn = ui.button("Execute utility", icon="sym_o_build").props("dense flat color=secondary")

        # Two columns: Left = Steps & Progress Cards, Right = Log Console
        with ui.element("div").classes("seimlai-runner-grid w-full"):
            # Left: Step progress list
            with ui.column().classes("seimlai-runner-stages w-full gap-2"):
                ui.label("Pipeline stages").classes("seimlai-runner-section-title")

                # Info banner for Stages 04 & 05 files
                with ui.row().classes(
                    "seimlai-alert seimlai-alert-info w-full items-center justify-between text-xs"
                ):
                    with ui.row().classes("items-center gap-1.5 flex-grow"):
                        ui.icon("sym_o_info").classes("text-primary text-base")
                        ui.label("Stages 04 & 05 require velocity models (grad.mod) & Fortran/Docker templates.").classes("text-xs")
                    if on_navigate_config:
                        ui.button("Edit / upload files", icon="sym_o_arrow_forward", on_click=on_navigate_config).props(
                            "flat dense color=primary text-xs"
                        ).classes("font-semibold")

                step_cards: dict[str, StepProgressCard] = {}
                for sid, state in pipeline_svc.step_states.items():
                    step_cards[sid] = StepProgressCard(state)

            # Right: Live Terminal Log Console
            with ui.column().classes("seimlai-runner-console w-full gap-2"):
                ui.label("Live console").classes("seimlai-runner-section-title")
                log_viewer = LogViewer(initial_logs=pipeline_svc.logs, height="440px")

        # Event Handlers & Reactivity
        def update_ui_running(is_running: bool):
            if is_running:
                status_icon.name = "sym_o_sync"
                status_icon.classes(replace="seimlai-runner-status text-primary animate-spin")
                overall_status_label.text = "Pipeline in progress..."
                run_all_btn.props("disable")
                continue_btn.props("disable")
                run_single_btn.props("disable")
                run_from_btn.props("disable")
                run_opt_btn.props("disable")
                stop_btn.classes(remove="hidden")
            else:
                status_icon.name = "sym_o_play_circle"
                status_icon.classes(replace="seimlai-runner-status text-gray-500")
                overall_status_label.text = "Execution finished / idle"
                run_all_btn.props(remove="disable")
                continue_btn.props(remove="disable")
                run_single_btn.props(remove="disable")
                run_from_btn.props(remove="disable")
                run_opt_btn.props(remove="disable")
                stop_btn.classes(add="hidden")

        def on_step_updated(step_id: str, state: StepState):
            if step_id in step_cards:
                step_cards[step_id].update(state)

        def on_new_log(line: str):
            log_viewer.append(line)

        def on_finished(success: bool, message: str):
            update_ui_running(False)
            status_icon.name = "sym_o_check_circle" if success else "sym_o_error"
            status_icon.classes(replace=f'seimlai-runner-status {"text-positive" if success else "text-negative"}')
            overall_status_label.text = "Workflow completed" if success else message
            if success:
                ui.notify(f"Pipeline finished successfully!", type="positive", icon="sym_o_check_circle")
            else:
                ui.notify(f"Execution halted: {message}", type="negative", icon="sym_o_error")

        if pipeline_svc.is_running:
            update_ui_running(True)

        # Wire service callbacks
        pipeline_svc.add_step_listener(on_step_updated)
        pipeline_svc.add_log_listener(on_new_log)
        pipeline_svc.add_finished_listener(on_finished)

        # Wire button click actions
        def trigger_run_all():
            update_ui_running(True)
            pipeline_svc.run_workflow_async(str(config_svc.config_path))

        def trigger_continue():
            update_ui_running(True)
            pipeline_svc.run_workflow_async(str(config_svc.config_path), from_step="04", phase_label="continue (04-05)")

        def trigger_run_single():
            sid = step_select.value
            update_ui_running(True)
            pipeline_svc.run_workflow_async(str(config_svc.config_path), only_steps=[sid], phase_label=f"single step {sid}")

        def trigger_run_from():
            sid = step_select.value
            update_ui_running(True)
            pipeline_svc.run_workflow_async(str(config_svc.config_path), from_step=sid, phase_label=f"from step {sid}")

        def trigger_stop():
            pipeline_svc.request_stop()
            ui.notify("Stopping pipeline...", type="warning")

        def trigger_optional():
            cmd = opt_select.value
            update_ui_running(True)
            pipeline_svc.run_optional_command_async(str(config_svc.config_path), cmd)

        run_all_btn.on("click", trigger_run_all)
        continue_btn.on("click", trigger_continue)
        run_single_btn.on("click", trigger_run_single)
        run_from_btn.on("click", trigger_run_from)
        stop_btn.on("click", trigger_stop)
        run_opt_btn.on("click", trigger_optional)

