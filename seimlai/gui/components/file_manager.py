"""File manager and code editor card for Stage 04 & 05 configuration files.

Provides file upload, in-browser code viewing, editing, and saving for:
- Stage 04 (HypoEllipse): grad.mod, improved.cfg
- Stage 05 (HypoDD): hypoDD.inc, ph2dt.inc, Dockerfile
"""

from __future__ import annotations

import datetime
from pathlib import Path
from nicegui import events, ui


def create_file_manager_card(
    title: str,
    target_dir: Path,
    default_files: list[str],
    help_text: str,
    file_extensions: str = ".mod,.cfg,.inc,.txt,.inp,.dat",
) -> None:
    """Render an interactive file manager and editor card."""
    target_dir.mkdir(parents=True, exist_ok=True)

    def get_existing_files() -> list[str]:
        found = set(default_files)
        if target_dir.exists():
            for p in target_dir.iterdir():
                if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".bak"):
                    found.add(p.name)
        # Ensure default files appear first in order
        ordered = [f for f in default_files if f in found]
        others = sorted([f for f in found if f not in default_files])
        return ordered + others

    files_list = get_existing_files()
    initial_file = files_list[0] if files_list else (default_files[0] if default_files else "")

    with ui.card().classes("w-full p-4 bg-slate-50 border border-slate-300 rounded-lg shadow-sm mt-3"):
        # Header
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                ui.icon("snippet_folder").classes("text-primary text-xl")
                ui.label(title).classes("font-bold text-slate-800 text-sm")
            ui.badge(str(target_dir), color="slate-700").classes("text-xs font-mono")

        ui.label(help_text).classes("text-xs text-slate-500 italic mt-1 mb-3")

        # Top Bar: File Selector & Actions
        with ui.row().classes("w-full items-center justify-between gap-3 flex-wrap mb-2"):
            with ui.row().classes("items-center gap-2 flex-grow"):
                ui.label("Selected File:").classes("text-xs font-bold text-slate-700")
                file_select = ui.select(
                    files_list,
                    value=initial_file,
                ).props("dense outlined").classes("w-56 text-xs bg-white rounded")

                file_stats_badge = ui.badge("", color="slate-200", text_color="slate-800").classes("text-xs font-mono border border-slate-300")

            with ui.row().classes("items-center gap-2"):
                save_btn = ui.button("Save file", icon="save", color="primary").props("unelevated dense text-xs py-1 px-3")
                reload_btn = ui.button("Reload", icon="refresh", color="secondary").props("outline dense text-xs py-1 px-2.5")

        # Code / Text Editor Area (Clean light background with crisp high-contrast text)
        editor = ui.textarea().props(
            "outlined autogrow=false "
            "input-class='font-mono text-xs text-slate-900' "
            "input-style='min-height: 220px; color: #0f172a; background-color: #ffffff; font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; line-height: 1.6; padding: 8px;'"
        ).classes("w-full bg-white rounded-lg shadow-sm border border-slate-200")

        # Helper to load file content into editor
        def load_current_file():
            fname = file_select.value
            if not fname:
                editor.value = ""
                file_stats_badge.text = "No file selected"
                return

            fpath = target_dir / fname
            if fpath.exists():
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                    editor.value = content
                    stat = fpath.stat()
                    dt = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                    file_stats_badge.text = f"{stat.st_size} B | {dt}"
                except Exception as exc:
                    editor.value = f"Error reading file: {exc}"
                    file_stats_badge.text = "Error"
            else:
                editor.value = ""
                file_stats_badge.text = "New file (not saved)"

        # Save current editor content
        def save_current_file():
            fname = file_select.value
            if not fname:
                ui.notify("No file selected to save", type="warning")
                return

            fpath = target_dir / fname
            try:
                # Backup if exists
                if fpath.exists():
                    bak_path = target_dir / f"{fname}.bak"
                    bak_path.write_text(fpath.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")

                fpath.write_text(editor.value or "", encoding="utf-8")
                load_current_file()
                ui.notify(f"Saved successfully: {fname}", type="positive", icon="check_circle")
            except Exception as exc:
                ui.notify(f"Failed to save {fname}: {exc}", type="negative", icon="error")

        save_btn.on("click", save_current_file)
        reload_btn.on("click", load_current_file)
        file_select.on_value_change(load_current_file)

        # Upload Widget (Drag & Drop or Pick file)
        ui.separator().classes("my-2")
        with ui.row().classes("w-full items-center justify-between gap-4"):
            with ui.column().classes("flex-grow gap-0"):
                ui.label("Upload or Replace File:").classes("text-xs font-bold text-slate-700")
                ui.label(f"Files are saved directly into {target_dir.name}/").classes("text-xs text-slate-400")

            async def handle_upload(e: events.UploadEventArguments):
                uploaded_name = e.file.name
                dest = target_dir / uploaded_name
                try:
                    await e.file.save(dest)
                    # Refresh file list
                    updated_files = get_existing_files()
                    file_select.options = updated_files
                    file_select.value = uploaded_name
                    load_current_file()
                    ui.notify(f"File uploaded: {uploaded_name}", type="positive", icon="cloud_done")
                except Exception as exc:
                    ui.notify(f"Upload failed: {exc}", type="negative", icon="cloud_off")

            ui.upload(
                label=f"Drag file here or browse ({file_extensions})",
                auto_upload=True,
                on_upload=handle_upload,
            ).props("dense bordered").classes("w-80 text-xs")

        # Initial load of selected file
        load_current_file()

