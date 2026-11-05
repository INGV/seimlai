"""Terminal-style log viewer UI component for SeiMLAI GUI.

Displays real-time streamed logs with autoscroll, search filter, and clear capability.
"""

from __future__ import annotations

from nicegui import ui


class LogViewer:
    """Scrollable, terminal-styled log console widget."""

    def __init__(self, initial_logs: list[str] | None = None, height: str = "320px"):
        self.height = height
        self._filter_text = ""
        self.autoscroll = True
        self.all_lines: list[str] = list(initial_logs or [])

        with ui.column().classes("seimlai-console w-full"):
            # Header controls
            with ui.row().classes("seimlai-console-toolbar w-full items-center justify-between"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_terminal").classes("text-slate-400 text-base")
                    ui.label("Execution logs").classes("font-semibold")
                    self.count_badge = ui.badge(str(len(self.all_lines)), color="secondary").classes("text-xs font-mono").tooltip("Total captured lines")

                with ui.row().classes("seimlai-console-actions items-center gap-2"):
                    self.search_input = ui.input(
                        placeholder="Filter logs...",
                        on_change=lambda e: self._on_filter_changed(e.value),
                    ).props('dense outlined clearable aria-label="Filter logs"').classes("seimlai-console-filter")

                    ui.button(
                        icon="sym_o_delete_sweep",
                        on_click=self.clear,
                    ).props('flat dense round color=secondary aria-label="Clear console"').tooltip("Clear console")

                    self.autoscroll_switch = ui.checkbox(
                        "Autoscroll",
                        value=True,
                        on_change=lambda e: setattr(self, "autoscroll", bool(e.value)),
                    ).props("dense color=primary")

            # Scrollable log content area
            self.scroll_area = ui.scroll_area().style(f"height: {self.height}; width: 100%;").classes("seimlai-console-body")
            with self.scroll_area:
                self.log_container = ui.column().classes("seimlai-log-lines w-full gap-0.5")

        if self.all_lines:
            self._render_all()

    def append(self, line: str) -> None:
        """Append a new log line."""
        self.all_lines.append(line)
        self.count_badge.text = str(len(self.all_lines))

        if not self._filter_text or self._filter_text.lower() in line.lower():
            with self.log_container:
                self._create_line_label(line)
            if self.autoscroll:
                self.scroll_area.scroll_to(percent=1.0)

    def _create_line_label(self, line: str) -> None:
        message = line.strip().upper()
        color_cls = "seimlai-log-default"
        if "[ERROR]" in message or "[FATAL]" in message or "[EXCEPTION]" in message or message.startswith("[!] ERROR"):
            color_cls = "seimlai-log-error"
        elif "[WARN]" in message or "[WARNING]" in message or "[HALTED]" in message:
            color_cls = "seimlai-log-warning"
        elif "[OK]" in message or "PIPELINE FINISHED SUCCESSFULLY" in message:
            color_cls = "seimlai-log-success"
        elif message.startswith(("SKIPPED ", "SKIPPED:", "[SKIP]")):
            color_cls = "seimlai-log-skipped"
        elif message.startswith(("DOWNLOADING ", ">> DOWNLOADING ")):
            color_cls = "seimlai-log-running"
        elif message.startswith(("===", "---", "###")):
            color_cls = "seimlai-log-section"

        ui.label(line).classes(f"seimlai-log-line {color_cls}")

    def clear(self) -> None:
        self.all_lines.clear()
        self.log_container.clear()
        self.count_badge.text = "0"

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text or ""
        self._render_all()

    def _render_all(self) -> None:
        self.log_container.clear()
        with self.log_container:
            for line in self.all_lines:
                if not self._filter_text or self._filter_text.lower() in line.lower():
                    self._create_line_label(line)
        if self.autoscroll:
            self.scroll_area.scroll_to(percent=1.0)

