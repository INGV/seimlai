"""Step progress UI component for SeiMLAI GUI.

Displays individual step card with status icon, description, progress bar,
and execution timing.
"""

from __future__ import annotations

from nicegui import ui
from seimlai.gui.services.pipeline_service import StepState


STATUS_ICONS = {
    "pending": ("sym_o_hourglass_empty", "text-gray-400"),
    "running": ("sym_o_sync", "text-primary animate-spin"),
    "done": ("sym_o_check_circle", "text-positive"),
    "error": ("sym_o_error", "text-negative"),
    "skipped": ("sym_o_skip_next", "text-gray-300"),
}

STATUS_COLORS = {
    "pending": "secondary",
    "running": "primary",
    "done": "positive",
    "error": "negative",
    "skipped": "secondary",
}


class StepProgressCard:
    """Renders and dynamically updates a single step progress row."""

    def __init__(self, step_state: StepState):
        self.step = step_state

        with ui.card().classes("seimlai-stage-card w-full").props(f'data-state="{self.step.status}"') as self.card:
            with ui.row().classes("seimlai-stage-heading w-full items-center justify-between no-wrap"):
                # Left: Step ID + Description
                with ui.row().classes("seimlai-stage-details items-center gap-3 no-wrap"):
                    ui.badge(self.step.id, color="secondary").classes("seimlai-stage-index font-mono")
                    with ui.column().classes("gap-0"):
                        ui.label(self.step.command).classes("seimlai-stage-title font-semibold text-sm text-gray-800")
                        ui.label(self.step.description).classes("text-xs text-gray-500")

                # Right: Status badge & elapsed time
                with ui.row().classes("seimlai-stage-state items-center gap-2 no-wrap"):
                    self.time_label = ui.label(f"{self.step.elapsed:.1f}s").classes("text-xs font-mono text-gray-500")
                    self.time_label.set_visibility(self.step.status == "done")
                    with ui.row().classes("items-center gap-1 no-wrap"):
                        icon_name, icon_cls = STATUS_ICONS.get(self.step.status, ("sym_o_help", "text-gray-400"))
                        self.icon = ui.icon(icon_name).classes(f"text-base {icon_cls}")
                        self.status_badge = ui.badge(self.step.status.capitalize(), color=STATUS_COLORS.get(self.step.status, "secondary")).classes("text-xs")

            # Progress Bar
            with ui.row().classes("seimlai-stage-progress w-full items-center gap-2") as self.progress_row:
                self.progress_bar = ui.linear_progress(
                    value=self.step.progress,
                    show_value=False,
                    color=STATUS_COLORS.get(self.step.status, "secondary"),
                    size="4px",
                ).classes("flex-grow rounded")
                self.pct_label = ui.label(f"{int(self.step.progress * 100)}%").classes("text-xs font-mono w-10 text-right text-gray-600")
            self.progress_row.set_visibility(self.step.status in ("running", "done"))

            # Error banner
            self.error_label = ui.label("").props("role=alert").classes("seimlai-alert seimlai-alert-error text-xs mt-1 hidden")
        self.update(self.step)

    def update(self, state: StepState) -> None:
        """Update reactive elements with new state."""
        self.step = state
        self.card.props(f'data-state="{state.status}"')

        # Icon
        icon_name, icon_cls = STATUS_ICONS.get(state.status, ("sym_o_help", "text-gray-400"))
        self.icon.name = icon_name
        self.icon.classes(replace=f"text-base {icon_cls}")

        # Status badge
        self.status_badge.text = state.status.capitalize()
        self.status_badge.props(f'color="{STATUS_COLORS.get(state.status, "secondary")}"')

        # Time
        self.time_label.text = f"{state.elapsed:.1f}s"
        self.time_label.set_visibility(state.status == "done")

        # Progress bar
        self.progress_bar.value = state.progress
        self.progress_bar.props(f'color="{STATUS_COLORS.get(state.status, "secondary")}"')
        self.pct_label.text = f"{int(state.progress * 100)}%"
        self.progress_row.set_visibility(state.status in ("running", "done"))

        # Error text
        if state.error_message and state.status == "error":
            self.error_label.text = f"Error: {state.error_message}"
            self.error_label.classes(remove="hidden")
        else:
            self.error_label.classes(add="hidden")

