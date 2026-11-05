"""Config Editor page for SeiMLAI GUI.

Displays all parameters from user_configuration/config.yaml in a single, comprehensive,
sectioned page with validation on save and a bounding-box mini-map.
"""

from __future__ import annotations

import json
from pathlib import Path
from nicegui import ui
from seimlai.gui.components.basemaps import BASEMAPS
from seimlai.gui.components.file_manager import create_file_manager_card
from seimlai.gui.services.config_service import ConfigService


def create_config_editor(config_svc: ConfigService):
    """Render all configurations on a single structured page."""

    field_refreshers = []
    refreshing = [False]
    invalid_fields = set()

    ui.add_body_html('<script src="/seimlai-assets/config-editor.js" defer></script>')
    with ui.column().classes("seimlai-config w-full gap-5") as config_page:

        # =====================================================================
        # CONFIGURATION HEADER & ACTION CALLBACKS
        # =====================================================================
        with ui.column().classes("seimlai-config-heading w-full"):
            with ui.row().classes("w-full items-center justify-between"):
                with ui.row().classes("items-center gap-3"):
                    ui.icon("sym_o_tune").classes("text-2xl text-primary")
                    with ui.column().classes("gap-0"):
                        ui.label("Configuration").classes("seimlai-config-title")
                        ui.label(f"Source: {config_svc.config_path}").classes("text-xs text-slate-500 font-mono")

                with ui.row().classes("seimlai-config-actions w-full items-center gap-2") as actions:
                    dirty_badge = ui.badge("Unsaved changes", color="amber-8").classes("text-xs mr-2 hidden")
                    if config_svc.is_dirty:
                        dirty_badge.classes(remove="hidden")

                    def update_dirty():
                        if config_svc.is_dirty or invalid_fields:
                            dirty_badge.classes(remove="hidden")
                            discard_btn.props('color=warning')
                        else:
                            dirty_badge.classes(add="hidden")
                            discard_btn.props('color=secondary')

                    def on_save():
                        try:
                            if invalid_fields:
                                raise ValueError("Invalid fields: " + ", ".join(sorted(invalid_fields)))
                            saved_path = config_svc.save()
                            ui.notify(f"Configuration saved: {saved_path}", type="positive", icon="save")
                            update_dirty()
                        except Exception as e:
                            ui.notify(f"Save failed: {e}", type="negative", icon="report_problem", multi_line=True)

                    def on_reset():
                        config_svc.reset_to_saved()
                        invalid_fields.clear()
                        refresh_fields()
                        ui.notify("Changes discarded.", type="info")

                    discard_btn = ui.button("Discard changes", icon="sym_o_undo", on_click=on_reset).props("flat dense color=secondary")
                    ui.button("Save configuration", icon="sym_o_save", on_click=on_save).props("unelevated dense color=primary")
                    update_dirty()

        # Section navigation
        with ui.element("nav").props('aria-label="Configuration sections"').classes("seimlai-config-nav w-full"):

            sections = [
                ("case_study", "Case study", "sym_o_folder"),
                ("geography", "Geography", "sym_o_public"),
                ("dates_stations", "Dates & stations", "sym_o_event"),
                ("model_cnn", "CNN model", "sym_o_psychology"),
                ("runtime", "Runtime", "sym_o_settings"),
                ("gamma", "GaMMA", "sym_o_hub"),
                ("hypoellipse", "HypoEllipse", "sym_o_my_location"),
                ("location_filtering", "Quality cuts", "sym_o_filter_alt"),
                ("hypodd", "HypoDD", "sym_o_auto_mode"),
                ("cc_dd", "Cross-correlation", "sym_o_graphic_eq"),
                ("plotting", "Plotting", "sym_o_bar_chart"),
            ]
            for sec_id, label, icon in sections:
                ui.button(
                    label,
                    icon=icon,
                    on_click=lambda sid=sec_id: ui.run_javascript(f"document.getElementById('{sid}')?.scrollIntoView({{behavior: 'smooth'}});"),
                ).props(f'dense flat color=secondary data-section="{sec_id}" aria-controls="{sec_id}"').classes("seimlai-section-link")

        # Helpers to bind scalar and list fields
        def bind_val(dot_key: str, widget, cast_type=None):
            field_refreshers.append(lambda: setattr(widget, "value", config_svc.get(dot_key)))
            def updater(e):
                if refreshing[0]:
                    return
                val = e.value
                if cast_type is not None and val is not None:
                    try:
                        val = cast_type(val)
                    except Exception:
                        pass
                if dot_key == "case_study.name" and val:
                    old_name = config_svc.get("case_study.name")
                    folder = config_svc.get("case_study.personal_folder")
                    if folder and Path(folder).resolve() == (Path.cwd() / "case_studies" / old_name).resolve():
                        cs_folder.value = str(Path.cwd() / "case_studies" / val)
                config_svc.set(dot_key, val)
                update_dirty()
            widget.on_value_change(updater)

        def bind_num_list(dot_key: str, widget, cast_elem=float):
            field_refreshers.append(lambda: setattr(widget, "value", ", ".join(str(v) for v in (config_svc.get(dot_key) or []))))
            def updater(e):
                if refreshing[0]:
                    return
                raw = e.value or ""
                try:
                    vals = [cast_elem(p.strip()) for p in raw.split(",") if p.strip()]
                    config_svc.set(dot_key, vals)
                    invalid_fields.discard(dot_key)
                except (ValueError, TypeError):
                    invalid_fields.add(dot_key)
                update_dirty()
            widget.on_value_change(updater)

        def bind_str_list(dot_key: str, widget):
            field_refreshers.append(lambda: setattr(widget, "value", ", ".join(str(v) for v in (config_svc.get(dot_key) or []))))
            def updater(e):
                if refreshing[0]:
                    return
                raw = e.value or ""
                vals = [p.strip() for p in raw.split(",") if p.strip()]
                config_svc.set(dot_key, vals)
                update_dirty()
            widget.on_value_change(updater)

        # =====================================================================
        # 1. CASE STUDY
        # =====================================================================
        with ui.card().props("id=case_study").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_folder").classes("text-xl text-primary")
                    ui.label("Case study & data source").classes("seimlai-config-section-title")
                ui.badge("case_study", color="slate-700").classes("text-xs font-mono")

            with ui.row().classes("seimlai-form-grid seimlai-case-grid w-full gap-4 items-center"):
                cs_name = ui.input("Case Study Name", value=config_svc.get("case_study.name", "case_study")).classes("w-64")
                bind_val("case_study.name", cs_name, str)

                cs_folder = ui.input(
                    "Personal Folder (Optional Custom Root)",
                    value=config_svc.get("case_study.personal_folder") or "",
                    placeholder="null for project-root directory",
                ).classes("flex-grow")

                field_refreshers.append(lambda: setattr(cs_folder, "value", config_svc.get("case_study.personal_folder") or ""))
                def on_personal_folder_change(e):
                    if refreshing[0]:
                        return
                    val = e.value.strip() if e.value else None
                    config_svc.set("case_study.personal_folder", val or None)
                    update_dirty()
                cs_folder.on_value_change(on_personal_folder_change)

            with ui.row().classes("w-full items-center mt-2"):
                dl_switch = ui.switch(
                    "Download Waveforms from FDSN (Stage 01)",
                    value=bool(config_svc.get("case_study.download_data", True)),
                ).props("color=primary")
                bind_val("case_study.download_data", dl_switch, bool)
                ui.label("If disabled and personal folder is set, the pipeline skips downloading and uses existing waveforms.").classes("text-xs text-slate-500 ml-2")

        # =====================================================================
        # 2. GEOGRAPHY
        # =====================================================================
        with ui.card().props("id=geography").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_public").classes("text-xl text-primary")
                    ui.label("Geography & bounding box").classes("seimlai-config-section-title")
                ui.badge("geography", color="slate-700").classes("text-xs font-mono")

            with ui.row().classes("seimlai-geography-grid w-full items-start"):
                # Left: Coordinate Inputs & Draw Button
                with ui.column().classes("seimlai-coordinate-fields gap-3"):
                    ui.label("Coordinate Bounds").classes("text-xs font-bold text-slate-600")
                    lat_min = ui.number("Min Latitude (°N)", value=config_svc.get("geography.minlatitude", 42.25), step=0.01, format="%.4f").classes("w-full")
                    lat_max = ui.number("Max Latitude (°N)", value=config_svc.get("geography.maxlatitude", 43.12), step=0.01, format="%.4f").classes("w-full")
                    lon_min = ui.number("Min Longitude (°E)", value=config_svc.get("geography.minlongitude", 11.75), step=0.01, format="%.4f").classes("w-full")
                    lon_max = ui.number("Max Longitude (°E)", value=config_svc.get("geography.maxlongitude", 14.00), step=0.01, format="%.4f").classes("w-full")

                    bind_val("geography.minlatitude", lat_min, float)
                    bind_val("geography.maxlatitude", lat_max, float)
                    bind_val("geography.minlongitude", lon_min, float)
                    bind_val("geography.maxlongitude", lon_max, float)

                    ui.separator().classes("my-1")

                    # Single Draw Bounding Box button
                    draw_state = {"active": False, "p1": None}
                    draw_btn = ui.button(
                        "Draw Bounding Box",
                        icon="crop_free",
                        color="primary",
                    ).props("unelevated dense").classes("w-full text-xs py-2")

                    draw_status = ui.label("Click 'Draw Bounding Box' to visually select an area on the map.").classes("text-xs text-slate-500 italic")

                # Right: Expanded Interactive Map (clean without Leaflet toolbar buttons)
                with ui.column().classes("seimlai-area-preview relative"):
                    with ui.row().classes("w-full items-center justify-between mb-1"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label("Interactive Area Selection Map").classes("text-xs font-bold text-slate-700")
                            mini_layer_select = ui.select(
                                {k: v["name"] for k, v in BASEMAPS.items()},
                                value="osm",
                            ).props("dense outlined").classes("w-44 text-xs")
                        coords_live_badge = ui.badge(
                            f"Lat: {float(lat_min.value):.2f} - {float(lat_max.value):.2f} | Lon: {float(lon_min.value):.2f} - {float(lon_max.value):.2f}",
                            color="secondary",
                        ).classes("seimlai-coordinate-readout text-xs font-mono")

                    c_lat = (float(config_svc.get("geography.minlatitude", 42.25)) + float(config_svc.get("geography.maxlatitude", 43.12))) / 2.0
                    c_lon = (float(config_svc.get("geography.minlongitude", 11.75)) + float(config_svc.get("geography.maxlongitude", 14.00))) / 2.0

                    # Map with NO toolbar buttons
                    mini_map = ui.leaflet(center=(c_lat, c_lon), zoom=7, draw_control=False).classes(
                        "w-full h-[480px] rounded-xl border border-slate-300 shadow-sm"
                    )

                    # Dynamic tile layer holder
                    tile_layer_holder = [
                        mini_map.tile_layer(
                            url_template=BASEMAPS["osm"]["url"],
                            options={"attribution": BASEMAPS["osm"]["attribution"], "maxZoom": BASEMAPS["osm"]["max_zoom"]},
                        )
                    ]

                    def on_mini_layer_change(e):
                        try:
                            mini_map.remove_layer(tile_layer_holder[0])
                        except Exception:
                            pass
                        bmap = BASEMAPS.get(e.value, BASEMAPS["osm"])
                        tile_layer_holder[0] = mini_map.tile_layer(
                            url_template=bmap["url"],
                            options={"attribution": bmap["attribution"], "maxZoom": bmap["max_zoom"]},
                        )

                    mini_layer_select.on_value_change(on_mini_layer_change)

                    # Initialize persistent rectangle layer
                    rect_layer = mini_map.generic_layer(
                        name="rectangle",
                        args=[
                            [[float(lat_min.value), float(lon_min.value)], [float(lat_max.value), float(lon_max.value)]],
                            {"color": "#2563eb", "weight": 2.5, "fillOpacity": 0.15},
                        ],
                    )

                    def update_map_rect(*_):
                        try:
                            mn_la = float(lat_min.value)
                            mx_la = float(lat_max.value)
                            mn_lo = float(lon_min.value)
                            mx_lo = float(lon_max.value)
                            rect_layer.run_method("setBounds", [[mn_la, mn_lo], [mx_la, mx_lo]])
                            coords_live_badge.text = f"Lat: {mn_la:.2f} - {mx_la:.2f} | Lon: {mn_lo:.2f} - {mx_lo:.2f}"
                        except Exception:
                            pass

                    def toggle_draw():
                        if draw_state["active"]:
                            draw_state["active"] = False
                            draw_state["p1"] = None
                            draw_btn.text = "Draw Bounding Box"
                            draw_btn.props('unelevated color="primary"')
                            draw_status.text = "Drawing cancelled. Reverted to previous box."
                            mini_map.classes(remove="cursor-crosshair")
                            update_map_rect()
                        else:
                            draw_state["active"] = True
                            draw_state["p1"] = None
                            draw_btn.text = "Cancel Drawing"
                            draw_btn.props('unelevated color="amber-8"')
                            draw_status.text = "1. Click on the map to place Corner 1..."
                            mini_map.classes(add="cursor-crosshair")
                            ui.notify("Click on the map to set Corner 1", type="info", icon="ads_click")

                    draw_btn.on("click", toggle_draw)

                    def on_map_click(e):
                        if not draw_state["active"]:
                            return
                        latlng = e.args.get("latlng", {})
                        click_lat = latlng.get("lat")
                        click_lon = latlng.get("lng")
                        if click_lat is None or click_lon is None:
                            return

                        if draw_state["p1"] is None:
                            draw_state["p1"] = (click_lat, click_lon)
                            draw_status.text = "2. Now move mouse to size the box, then click again to finish!"
                        else:
                            p1 = draw_state["p1"]
                            p2 = (click_lat, click_lon)

                            n_minlat = round(min(p1[0], p2[0]), 4)
                            n_maxlat = round(max(p1[0], p2[0]), 4)
                            n_minlon = round(min(p1[1], p2[1]), 4)
                            n_maxlon = round(max(p1[1], p2[1]), 4)

                            lat_min.value = n_minlat
                            lat_max.value = n_maxlat
                            lon_min.value = n_minlon
                            lon_max.value = n_maxlon

                            config_svc.set("geography.minlatitude", n_minlat)
                            config_svc.set("geography.maxlatitude", n_maxlat)
                            config_svc.set("geography.minlongitude", n_minlon)
                            config_svc.set("geography.maxlongitude", n_maxlon)
                            update_dirty()

                            draw_state["active"] = False
                            draw_state["p1"] = None
                            draw_btn.text = "Draw Bounding Box"
                            draw_btn.props('unelevated color="primary"')
                            mini_map.classes(remove="cursor-crosshair")
                            draw_status.text = f"Box locked: Lat [{n_minlat:.2f}, {n_maxlat:.2f}], Lon [{n_minlon:.2f}, {n_maxlon:.2f}]"
                            update_map_rect()
                            ui.notify(
                                f"Bounding box set: Lat [{n_minlat:.2f}, {n_maxlat:.2f}], Lon [{n_minlon:.2f}, {n_maxlon:.2f}]",
                                type="positive",
                                icon="check_circle",
                            )

                    mini_map.on("map-click", on_map_click)

                    def on_map_mousemove(e):
                        if not draw_state["active"] or draw_state["p1"] is None:
                            return
                        latlng = e.args.get("latlng", {})
                        m_lat = latlng.get("lat")
                        m_lon = latlng.get("lng")
                        if m_lat is None or m_lon is None:
                            return

                        p1 = draw_state["p1"]
                        c_minlat = round(min(p1[0], m_lat), 4)
                        c_maxlat = round(max(p1[0], m_lat), 4)
                        c_minlon = round(min(p1[1], m_lon), 4)
                        c_maxlon = round(max(p1[1], m_lon), 4)

                        lat_min.value = c_minlat
                        lat_max.value = c_maxlat
                        lon_min.value = c_minlon
                        lon_max.value = c_maxlon
                        coords_live_badge.text = f"Lat: {c_minlat:.4f} → {c_maxlat:.4f} | Lon: {c_minlon:.4f} → {c_maxlon:.4f}"
                        rect_layer.run_method("setBounds", [[c_minlat, c_minlon], [c_maxlat, c_maxlon]])

                    mini_map.on("map-mousemove", on_map_mousemove)

                    lat_min.on_value_change(update_map_rect)
                    lat_max.on_value_change(update_map_rect)
                    lon_min.on_value_change(update_map_rect)
                    lon_max.on_value_change(update_map_rect)

        # =====================================================================
        # 3. DATES & STATIONS
        # =====================================================================
        with ui.card().props("id=dates_stations").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_event").classes("text-xl text-primary")
                    ui.label("Dates & stations").classes("seimlai-config-section-title")
                ui.badge("dates & stations", color="slate-700").classes("text-xs font-mono")

            # Dates row
            with ui.row().classes("seimlai-form-grid seimlai-form-grid-2 w-full gap-4 mb-3"):
                st_date = ui.input("Start Date (YYYY-MM-DD)", value=str(config_svc.get("dates.starttime", "2016-10-30"))).classes("w-64")
                et_date = ui.input("End Date (YYYY-MM-DD)", value=str(config_svc.get("dates.endtime", "2016-10-30"))).classes("w-64")
                bind_val("dates.starttime", st_date, str)
                bind_val("dates.endtime", et_date, str)

            ui.separator().classes("my-2")

            # Stations row
            with ui.row().classes("seimlai-form-grid seimlai-form-grid-3 w-full gap-4"):
                net_in = ui.input("Network (* for all)", value=config_svc.get("stations.network", "*")).classes("w-40")
                chan_in = ui.input("Channel Pattern", value=config_svc.get("stations.channel", "BH?,HH?,EH?")).classes("w-56")
                sta_in = ui.input("Stations List (* for all or comma-separated)", value=config_svc.get("stations.stations_list", "*")).classes("flex-grow")

                bind_val("stations.network", net_in, str)
                bind_val("stations.channel", chan_in, str)
                bind_val("stations.stations_list", sta_in, str)

            with ui.row().classes("seimlai-form-grid w-full gap-4 mt-2"):
                fdsn_raw = config_svc.get("stations.fdsn_clients", ["IRIS", "INGV"])
                fdsn_str = ", ".join(fdsn_raw) if isinstance(fdsn_raw, list) else str(fdsn_raw)
                fdsn_in = ui.input("FDSN Data Centers (comma-separated)", value=fdsn_str).classes("seimlai-field-wide")
                bind_str_list("stations.fdsn_clients", fdsn_in)

        # =====================================================================
        # 4. DEEP LEARNING MODEL (PHASENET / EQTRANSFORMER)
        # =====================================================================
        with ui.card().props("id=model_cnn").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_psychology").classes("text-xl text-primary")
                    ui.label("CNN phase picking").classes("seimlai-config-section-title")
                ui.badge("model", color="slate-700").classes("text-xs font-mono")

            with ui.row().classes("seimlai-form-grid seimlai-model-grid w-full gap-4"):
                nn_sel = ui.select(["PhaseNet", "EQTransformer"], value=config_svc.get("model.neural_network", "PhaseNet"), label="Neural Network").classes("w-48")
                mtype_in = ui.input("Pretrained Model Type", value=config_svc.get("model.model_type", "original")).classes("w-48")
                batch_in = ui.number("Batch Size", value=config_svc.get("model.batch_size", 256), step=16).classes("w-32")
                custom_model = ui.input("Custom Model Path (.pth / null)", value=config_svc.get("model.custom_model_path") or "").classes("flex-grow")

                bind_val("model.neural_network", nn_sel, str)
                bind_val("model.model_type", mtype_in, str)
                bind_val("model.batch_size", batch_in, int)

                field_refreshers.append(lambda: setattr(custom_model, "value", config_svc.get("model.custom_model_path") or ""))
                def on_custom_model_change(e):
                    if refreshing[0]:
                        return
                    val = e.value.strip() if e.value else None
                    config_svc.set("model.custom_model_path", val or None)
                    update_dirty()
                custom_model.on_value_change(on_custom_model_change)

            with ui.row().classes("seimlai-form-grid seimlai-form-grid-2 w-full gap-8 mt-4"):
                with ui.column().classes("w-80"):
                    ui.label("P-wave Pick Detection Threshold").classes("text-xs font-semibold text-slate-700")
                    p_val = float(config_svc.get("model.p_threshold", 0.5))
                    p_slider = ui.slider(min=0.1, max=0.9, step=0.05, value=p_val).props("label-always color=primary")
                    bind_val("model.p_threshold", p_slider, float)

                with ui.column().classes("w-80"):
                    ui.label("S-wave Pick Detection Threshold").classes("text-xs font-semibold text-slate-700")
                    s_val = float(config_svc.get("model.s_threshold", 0.5))
                    s_slider = ui.slider(min=0.1, max=0.9, step=0.05, value=s_val).props("label-always color=primary")
                    bind_val("model.s_threshold", s_slider, float)

        # =====================================================================
        # 5. RUNTIME & FILTERS
        # =====================================================================
        with ui.card().props("id=runtime").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_settings").classes("text-xl text-primary")
                    ui.label("Runtime & waveform filters").classes("seimlai-config-section-title")
                ui.badge("phase_picking", color="slate-700").classes("text-xs font-mono")

            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                workers = ui.number("CPU / MPS Worker Cores", value=config_svc.get("phase_picking.num_workers_cpu_mps", 2), step=1).classes("w-48")
                slurm = ui.number("SLURM Fallback CPU Cores", value=config_svc.get("phase_picking.slurm_cpus_default", 4), step=1).classes("w-48")
                fmin = ui.number("Bandpass Min Freq (Hz)", value=config_svc.get("phase_picking.bandpass_freq_min", 0.5), step=0.1).classes("w-48")
                fmax = ui.number("Bandpass Max Freq (Hz)", value=config_svc.get("phase_picking.bandpass_freq_max", 30.0), step=1.0).classes("w-48")

                bind_val("phase_picking.num_workers_cpu_mps", workers, int)
                bind_val("phase_picking.slurm_cpus_default", slurm, int)
                bind_val("phase_picking.bandpass_freq_min", fmin, float)
                bind_val("phase_picking.bandpass_freq_max", fmax, float)

        # =====================================================================
        # 6. GAMMA PHASE ASSOCIATION
        # =====================================================================
        with ui.card().props("id=gamma").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_hub").classes("text-xl text-primary")
                    ui.label("GaMMA association").classes("seimlai-config-section-title")
                ui.badge("gamma", color="slate-700").classes("text-xs font-mono")

            # Method & Velocities
            with ui.row().classes("seimlai-form-grid w-full gap-4 items-center"):
                g_meth = ui.select(["BGMM", "GMM"], value=config_svc.get("gamma.method", "BGMM"), label="Association Method").classes("w-44")
                bind_val("gamma.method", g_meth, str)

                g_vp = ui.number("Velocity P (km/s)", value=config_svc.get("gamma.velocity.p", 7.0), step=0.1).classes("w-36")
                g_vs = ui.number("Velocity S (km/s)", value=config_svc.get("gamma.velocity.s", 4.0), step=0.1).classes("w-36")
                bind_val("gamma.velocity.p", g_vp, float)
                bind_val("gamma.velocity.s", g_vs, float)

                dbscan_sw = ui.switch("Use DBSCAN", value=bool(config_svc.get("gamma.use_dbscan", True))).props("color=primary")
                amp_sw = ui.switch("Use Amplitude", value=bool(config_svc.get("gamma.use_amplitude", True))).props("color=primary")
                bind_val("gamma.use_dbscan", dbscan_sw, bool)
                bind_val("gamma.use_amplitude", amp_sw, bool)

            # Volume Limits (UTM)
            ui.separator().classes("my-2")
            ui.label("Search Volume Bounds in UTM (km)").classes("text-xs font-bold text-slate-600 mb-1")
            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                x_km_str = ", ".join(str(v) for v in config_svc.get("gamma.x_km", [230, 620]))
                y_km_str = ", ".join(str(v) for v in config_svc.get("gamma.y_km", [4650, 4800]))
                z_km_str = ", ".join(str(v) for v in config_svc.get("gamma.z_km", [0, 60]))

                x_km_in = ui.input("X Range [min, max] km", value=x_km_str).classes("w-52")
                y_km_in = ui.input("Y Range [min, max] km", value=y_km_str).classes("w-52")
                z_km_in = ui.input("Z Depth [min, max] km", value=z_km_str).classes("w-52")

                bind_num_list("gamma.x_km", x_km_in, int)
                bind_num_list("gamma.y_km", y_km_in, int)
                bind_num_list("gamma.z_km", z_km_in, int)

                deps_in = ui.number("DBSCAN eps (km)", value=config_svc.get("gamma.dbscan_eps", 25), step=1).classes("w-36")
                dmins_in = ui.number("DBSCAN min samples", value=config_svc.get("gamma.dbscan_min_samples", 3), step=1).classes("w-36")
                bind_val("gamma.dbscan_eps", deps_in, int)
                bind_val("gamma.dbscan_min_samples", dmins_in, int)

            # Filtering Criteria
            ui.separator().classes("my-2")
            ui.label("GaMMA Quality Filtering & Sigmas").classes("text-xs font-bold text-slate-600 mb-1")
            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                min_picks = ui.number("Min Total Picks", value=config_svc.get("gamma.filtering.min_picks_per_eq", 6), step=1).classes("w-36")
                min_p = ui.number("Min P Picks", value=config_svc.get("gamma.filtering.min_p_picks_per_eq", 4), step=1).classes("w-36")
                min_s = ui.number("Min S Picks", value=config_svc.get("gamma.filtering.min_s_picks_per_eq", 3), step=1).classes("w-36")
                s11 = ui.number("Max Sigma11", value=config_svc.get("gamma.filtering.max_sigma11", 1.5), step=0.1).classes("w-32")
                s22 = ui.number("Max Sigma22", value=config_svc.get("gamma.filtering.max_sigma22", 1.0), step=0.1).classes("w-32")
                s12 = ui.number("Max Sigma12", value=config_svc.get("gamma.filtering.max_sigma12", 1.0), step=0.1).classes("w-32")

                bind_val("gamma.filtering.min_picks_per_eq", min_picks, int)
                bind_val("gamma.filtering.min_p_picks_per_eq", min_p, int)
                bind_val("gamma.filtering.min_s_picks_per_eq", min_s, int)
                bind_val("gamma.filtering.max_sigma11", s11, float)
                bind_val("gamma.filtering.max_sigma22", s22, float)
                bind_val("gamma.filtering.max_sigma12", s12, float)

            # Eikonal Model
            ui.separator().classes("my-2")
            ui.label("Eikonal Velocity Model (1D Layers)").classes("text-xs font-bold text-slate-600 mb-1")
            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                eik_ratio = ui.number("Vp/Vs Ratio", value=config_svc.get("gamma.eikonal.vp_vs_ratio", 1.73), step=0.01).classes("w-32")
                eik_h = ui.number("Layer Thickness h (km)", value=config_svc.get("gamma.eikonal.h", 1.0), step=0.1).classes("w-40")
                bind_val("gamma.eikonal.vp_vs_ratio", eik_ratio, float)
                bind_val("gamma.eikonal.h", eik_h, float)

                eik_z_str = ", ".join(str(v) for v in config_svc.get("gamma.eikonal.z", [0.0, 5.5, 16.0, 32.0]))
                eik_p_str = ", ".join(str(v) for v in config_svc.get("gamma.eikonal.p", [5.5, 5.5, 6.7, 7.8]))
                eik_z_in = ui.input("Layer Depths z (km, comma-sep)", value=eik_z_str).classes("flex-grow")
                eik_p_in = ui.input("P-wave Velocities (km/s, comma-sep)", value=eik_p_str).classes("flex-grow")
                bind_num_list("gamma.eikonal.z", eik_z_in, float)
                bind_num_list("gamma.eikonal.p", eik_p_in, float)

        # =====================================================================
        # 7. HYPOELLIPSE (ABSOLUTE LOCATION)
        # =====================================================================
        with ui.card().props("id=hypoellipse").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_my_location").classes("text-xl text-primary")
                    ui.label("HypoEllipse absolute location").classes("seimlai-config-section-title")
                ui.badge("hypoellipse & hypoellipse_check", color="slate-700").classes("text-xs font-mono")

            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                h71_p = ui.number("Min P-picks per EQ (H71)", value=config_svc.get("hypoellipse.h71_min_p", 4), step=1).classes("w-48")
                h71_s = ui.number("Min S-picks per EQ (H71)", value=config_svc.get("hypoellipse.h71_min_s", 2), step=1).classes("w-48")
                docker_img = ui.input("HypoEllipse Docker Image", value=config_svc.get("hypoellipse_check.docker_image", "ingv/hypoellipse")).classes("w-64")
                docker_timeout = ui.number("Docker Start Timeout (s)", value=config_svc.get("hypoellipse_check.docker_start_timeout_seconds", 90), step=10).classes("w-44")

                bind_val("hypoellipse.h71_min_p", h71_p, int)
                bind_val("hypoellipse.h71_min_s", h71_s, int)
                bind_val("hypoellipse_check.docker_image", docker_img, str)
                bind_val("hypoellipse_check.docker_start_timeout_seconds", docker_timeout, int)

            # HypoEllipse Required Model & Parameter Files (Stage 04)
            create_file_manager_card(
                title="Stage 04 Required Files: Velocity Model & Run Configuration",
                target_dir=Path("user_configuration/hypoellipse"),
                default_files=["grad.mod", "improved.cfg"],
                help_text="HypoEllipse requires a 1D crustal velocity model (grad.mod) and a parameters file (improved.cfg). You can view, edit, or upload custom velocity models here.",
                file_extensions=".mod,.cfg,.txt",
            )

        # =====================================================================
        # 8. LOCATION FILTERING (QUALITY CUTS)
        # =====================================================================
        with ui.card().props("id=location_filtering").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_filter_alt").classes("text-xl text-primary")
                    ui.label("Location quality cuts").classes("seimlai-config-section-title")
                ui.badge("dd", color="slate-700").classes("text-xs font-mono")

            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                max_gap = ui.number("Max Azimuthal Gap (°)", value=config_svc.get("dd.max_gap", 180.0), step=5.0).classes("w-44")
                max_rms = ui.number("Max RMS Residual (s)", value=config_svc.get("dd.max_rms", 0.8), step=0.05).classes("w-44")
                max_erh = ui.number("Max Horizontal Error ERH (km)", value=config_svc.get("dd.max_erh", 2.0), step=0.1).classes("w-52")
                max_erz = ui.number("Max Vertical Error ERZ (km)", value=config_svc.get("dd.max_erz", 2.0), step=0.1).classes("w-52")

                bind_val("dd.max_gap", max_gap, float)
                bind_val("dd.max_rms", max_rms, float)
                bind_val("dd.max_erh", max_erh, float)
                bind_val("dd.max_erz", max_erz, float)

        # =====================================================================
        # 9. HYPODD RELOCATION
        # =====================================================================
        with ui.card().props("id=hypodd").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_auto_mode").classes("text-xl text-primary")
                    ui.label("HypoDD relative relocation").classes("seimlai-config-section-title")
                ui.badge("hypodd", color="slate-700").classes("text-xs font-mono")

            # General & Docker
            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                hd_img = ui.input("HypoDD Docker Image", value=config_svc.get("hypodd.docker_image", "hypodd:2.1b")).classes("w-60")
                hd_timeout = ui.number("Docker Timeout (s)", value=config_svc.get("hypodd.docker_start_timeout_seconds", 90), step=10).classes("w-36")
                dim_mode = ui.select(["auto", "manual"], value=config_svc.get("hypodd.dimensions.mode", "auto"), label="Dimension Mode").classes("w-36")
                maxeve0 = ui.number("maxeve0", value=config_svc.get("hypodd.dimensions.maxeve0", 1), step=1).classes("w-28")
                maxlay = ui.number("maxlay", value=config_svc.get("hypodd.dimensions.maxlay", 14), step=1).classes("w-28")
                maxcl = ui.number("maxcl", value=config_svc.get("hypodd.dimensions.maxcl", 30), step=1).classes("w-28")

                bind_val("hypodd.docker_image", hd_img, str)
                bind_val("hypodd.docker_start_timeout_seconds", hd_timeout, int)
                bind_val("hypodd.dimensions.mode", dim_mode, str)
                bind_val("hypodd.dimensions.maxeve0", maxeve0, int)
                bind_val("hypodd.dimensions.maxlay", maxlay, int)
                bind_val("hypodd.dimensions.maxcl", maxcl, int)

            # ph2dt parameters
            ui.separator().classes("my-2")
            ui.label("ph2dt Input Parameters").classes("text-xs font-bold text-slate-600 mb-1")
            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                p_minw = ui.number("Min Weight", value=config_svc.get("hypodd.ph2dt.min_weight", 0.0), step=0.1).classes("w-32")
                p_maxdist = ui.number("Max Dist (km)", value=config_svc.get("hypodd.ph2dt.max_dist_km", 150.0), step=10.0).classes("w-36")
                p_maxsep = ui.number("Max Sep (km)", value=config_svc.get("hypodd.ph2dt.max_sep_km", 10.0), step=1.0).classes("w-36")
                p_maxneigh = ui.number("Max Neighbors", value=config_svc.get("hypodd.ph2dt.max_neighbors", 30), step=5).classes("w-36")
                p_minlinks = ui.number("Min Links", value=config_svc.get("hypodd.ph2dt.min_links", 8), step=1).classes("w-32")
                p_minobs = ui.number("Min Observations", value=config_svc.get("hypodd.ph2dt.min_observations", 8), step=1).classes("w-36")
                p_maxobs = ui.number("Max Observations", value=config_svc.get("hypodd.ph2dt.max_observations", 30), step=5).classes("w-36")

                bind_val("hypodd.ph2dt.min_weight", p_minw, float)
                bind_val("hypodd.ph2dt.max_dist_km", p_maxdist, float)
                bind_val("hypodd.ph2dt.max_sep_km", p_maxsep, float)
                bind_val("hypodd.ph2dt.max_neighbors", p_maxneigh, int)
                bind_val("hypodd.ph2dt.min_links", p_minlinks, int)
                bind_val("hypodd.ph2dt.min_observations", p_minobs, int)
                bind_val("hypodd.ph2dt.max_observations", p_maxobs, int)

            # Relocation flags
            ui.separator().classes("my-2")
            ui.label("HypoDD Inversion & Solver Settings").classes("text-xs font-bold text-slate-600 mb-1")
            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                idat = ui.number("idat", value=config_svc.get("hypodd.relocation.idat", 3), step=1).classes("w-24")
                ipha = ui.number("ipha", value=config_svc.get("hypodd.relocation.ipha", 3), step=1).classes("w-24")
                r_maxdist = ui.number("Max Dist (km)", value=config_svc.get("hypodd.relocation.max_dist_km", 50.0), step=5.0).classes("w-36")
                obscc = ui.number("obscc", value=config_svc.get("hypodd.relocation.obscc", 3), step=1).classes("w-24")
                obsct = ui.number("obsct", value=config_svc.get("hypodd.relocation.obsct", 13), step=1).classes("w-24")
                istart = ui.number("istart", value=config_svc.get("hypodd.relocation.istart", 2), step=1).classes("w-24")
                isolve = ui.number("isolve", value=config_svc.get("hypodd.relocation.isolve", 2), step=1).classes("w-24")

                bind_val("hypodd.relocation.idat", idat, int)
                bind_val("hypodd.relocation.ipha", ipha, int)
                bind_val("hypodd.relocation.max_dist_km", r_maxdist, float)
                bind_val("hypodd.relocation.obscc", obscc, int)
                bind_val("hypodd.relocation.obsct", obsct, int)
                bind_val("hypodd.relocation.istart", istart, int)
                bind_val("hypodd.relocation.isolve", isolve, int)

            # HypoDD 1D Velocity Model
            ui.separator().classes("my-2")
            ui.label("HypoDD 1D Velocity Model Layers").classes("text-xs font-bold text-slate-600 mb-1")
            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                hd_ratio = ui.number("Vp/Vs Ratio", value=config_svc.get("hypodd.velocity_model.vp_vs_ratio", 1.86), step=0.01).classes("w-32")
                bind_val("hypodd.velocity_model.vp_vs_ratio", hd_ratio, float)

                top_km_raw = config_svc.get("hypodd.velocity_model.top_km", [])
                top_km_str = ", ".join(str(v) for v in top_km_raw)
                top_km_in = ui.input("Layer Top Depths top_km (comma-separated)", value=top_km_str).classes("seimlai-field-wide")
                bind_num_list("hypodd.velocity_model.top_km", top_km_in, float)

            with ui.row().classes("seimlai-form-grid w-full gap-4 mt-1"):
                vp_km_raw = config_svc.get("hypodd.velocity_model.vp_km_s", [])
                vp_km_str = ", ".join(str(v) for v in vp_km_raw)
                vp_km_in = ui.input("Layer Velocities vp_km_s (comma-separated)", value=vp_km_str).classes("seimlai-field-full")
                bind_num_list("hypodd.velocity_model.vp_km_s", vp_km_in, float)

            # Iteration sets
            ui.separator().classes("my-2")
            ui.label("HypoDD Iteration Sets (JSON Array)").classes("text-xs font-bold text-slate-600 mb-1")
            iter_sets_raw = config_svc.get("hypodd.relocation.iteration_sets", [])
            iter_sets_in = ui.textarea(value=json.dumps(iter_sets_raw, indent=2)).props(
                "outlined autogrow=false input-class='font-mono text-xs text-slate-900' input-style='min-height: 140px; color: #0f172a; background-color: #ffffff;'"
            ).classes("w-full font-mono text-xs bg-white rounded-lg")

            field_refreshers.append(lambda: setattr(iter_sets_in, "value", json.dumps(config_svc.get("hypodd.relocation.iteration_sets", []), indent=2)))
            def on_iter_sets_change(e):
                if refreshing[0]:
                    return
                try:
                    parsed = json.loads(e.value)
                    if not isinstance(parsed, list):
                        raise ValueError("Expected an array")
                    config_svc.set("hypodd.relocation.iteration_sets", parsed)
                    invalid_fields.discard("hypodd.relocation.iteration_sets")
                except (ValueError, TypeError):
                    invalid_fields.add("hypodd.relocation.iteration_sets")
                update_dirty()
            iter_sets_in.on_value_change(on_iter_sets_change)

            # HypoDD Required Fortran Dimension Templates & Dockerfile (Stage 05)
            create_file_manager_card(
                title="Stage 05 Required Files: Fortran Dimensions & Dockerfile",
                target_dir=Path("user_configuration/hypodd"),
                default_files=["hypoDD.inc", "ph2dt.inc", "Dockerfile"],
                help_text="HypoDD compiles and runs with Fortran include templates (hypoDD.inc, ph2dt.inc) and a Dockerfile. You can edit dimension parameters or upload custom includes here.",
                file_extensions=".inc,.Dockerfile,.txt,.inp",
            )

        # =====================================================================
        # 10. CROSS-CORRELATION (CC_DD)
        # =====================================================================
        with ui.card().props("id=cc_dd").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_graphic_eq").classes("text-xl text-primary")
                    ui.label("Cross-correlation (CC-DD)").classes("seimlai-config-section-title")
                ui.badge("cc_dd", color="slate-700").classes("text-xs font-mono")

            # Hardware & general
            with ui.row().classes("seimlai-form-grid w-full gap-4 items-center"):
                gpu_sw = ui.switch("Use GPU Acceleration", value=bool(config_svc.get("cc_dd.use_gpu", True))).props("color=primary")
                bind_val("cc_dd.use_gpu", gpu_sw, bool)

                gpu_bs = ui.input("GPU Batch Size", value=str(config_svc.get("cc_dd.gpu_batch_size", "auto"))).classes("w-40")
                bind_val("cc_dd.gpu_batch_size", gpu_bs, str)

                max_dist_cc = ui.number("Max Dist CC (km)", value=config_svc.get("cc_dd.max_dist_km_cc", 3.0), step=0.5).classes("w-40")
                bind_val("cc_dd.max_dist_km_cc", max_dist_cc, float)

                cc_th = ui.number("CC Threshold", value=config_svc.get("cc_dd.cc_threshold", 0.8), step=0.05).classes("w-36")
                snr_th = ui.number("SNR Threshold", value=config_svc.get("cc_dd.snr_threshold", 1.0), step=0.1).classes("w-36")
                dt_max = ui.number("Max Abs dt (s)", value=config_svc.get("cc_dd.max_abs_dt_seconds", 2.0), step=0.1).classes("w-36")

                bind_val("cc_dd.cc_threshold", cc_th, float)
                bind_val("cc_dd.snr_threshold", snr_th, float)
                bind_val("cc_dd.max_abs_dt_seconds", dt_max, float)

            # Windows & Filters
            ui.separator().classes("my-2")
            ui.label("P-wave & S-wave Time Windows & Lag (seconds)").classes("text-xs font-bold text-slate-600 mb-1")
            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                p_bef = ui.number("P Win Before (s)", value=config_svc.get("cc_dd.p_win_before", 0.2), step=0.05).classes("w-36")
                p_aft = ui.number("P Win After (s)", value=config_svc.get("cc_dd.p_win_after", 1.0), step=0.1).classes("w-36")
                p_lag = ui.number("P Max Lag (s)", value=config_svc.get("cc_dd.p_max_lag", 0.3), step=0.05).classes("w-36")

                s_bef = ui.number("S Win Before (s)", value=config_svc.get("cc_dd.s_win_before", 0.5), step=0.05).classes("w-36")
                s_aft = ui.number("S Win After (s)", value=config_svc.get("cc_dd.s_win_after", 1.5), step=0.1).classes("w-36")
                s_lag = ui.number("S Max Lag (s)", value=config_svc.get("cc_dd.s_max_lag", 0.5), step=0.05).classes("w-36")

                bind_val("cc_dd.p_win_before", p_bef, float)
                bind_val("cc_dd.p_win_after", p_aft, float)
                bind_val("cc_dd.p_max_lag", p_lag, float)
                bind_val("cc_dd.s_win_before", s_bef, float)
                bind_val("cc_dd.s_win_after", s_aft, float)
                bind_val("cc_dd.s_max_lag", s_lag, float)

            # Channels & Pairing
            ui.separator().classes("my-2")
            ui.label("Component Channels, Bandpass & Pairing Limits").classes("text-xs font-bold text-slate-600 mb-1")
            with ui.row().classes("seimlai-form-grid w-full gap-4 items-center"):
                cc_fmin = ui.number("Freq Min (Hz)", value=config_svc.get("cc_dd.freq_min", 2.0), step=0.5).classes("w-32")
                cc_fmax = ui.number("Freq Max (Hz)", value=config_svc.get("cc_dd.freq_max", 15.0), step=1.0).classes("w-32")
                pad_sec = ui.number("Filter Pad (s)", value=config_svc.get("cc_dd.filter_pad_seconds", 1.0), step=0.1).classes("w-32")

                bind_val("cc_dd.freq_min", cc_fmin, float)
                bind_val("cc_dd.freq_max", cc_fmax, float)
                bind_val("cc_dd.filter_pad_seconds", pad_sec, float)

                p_chan = ui.input("P Channel", value=config_svc.get("cc_dd.p_channel", "??Z")).classes("w-28")
                se_chan = ui.input("S-East Channel", value=config_svc.get("cc_dd.s_e_channel", "??E")).classes("w-28")
                sn_chan = ui.input("S-North Channel", value=config_svc.get("cc_dd.s_n_channel", "??N")).classes("w-28")
                req_both_s = ui.switch("Require Both S", value=bool(config_svc.get("cc_dd.require_both_s_components", True))).props("color=primary")

                bind_val("cc_dd.p_channel", p_chan, str)
                bind_val("cc_dd.s_e_channel", se_chan, str)
                bind_val("cc_dd.s_n_channel", sn_chan, str)
                bind_val("cc_dd.require_both_s_components", req_both_s, bool)

            with ui.row().classes("seimlai-form-grid w-full gap-4 mt-2"):
                min_cp = ui.number("Min Common Picks", value=config_svc.get("cc_dd.min_common_picks_per_pair", 8), step=1).classes("w-40")
                min_read = ui.number("Min Readings/Pair", value=config_svc.get("cc_dd.min_readings_per_pair", 4), step=1).classes("w-40")
                edge_marg = ui.number("Peak Edge Margin (s)", value=config_svc.get("cc_dd.peak_edge_margin_seconds", 0.01), step=0.005).classes("w-44")
                shift_tol = ui.number("S Shift Tol (s)", value=config_svc.get("cc_dd.s_shift_tolerance_seconds", 0.02), step=0.005).classes("w-40")

                bind_val("cc_dd.min_common_picks_per_pair", min_cp, int)
                bind_val("cc_dd.min_readings_per_pair", min_read, int)
                bind_val("cc_dd.peak_edge_margin_seconds", edge_marg, float)
                bind_val("cc_dd.s_shift_tolerance_seconds", shift_tol, float)

        # =====================================================================
        # 11. PLOTTING, ANALYSIS & THRESHOLD ANALYSIS
        # =====================================================================
        with ui.card().props("id=plotting").classes("seimlai-config-section w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.row().classes("items-center gap-2"):
                    ui.icon("sym_o_bar_chart").classes("text-xl text-primary")
                    ui.label("Plotting & analysis").classes("seimlai-config-section-title")
                ui.badge("plotting, analysis & threshold_analysis", color="slate-700").classes("text-xs font-mono")

            with ui.row().classes("seimlai-form-grid w-full gap-4"):
                mtitle = ui.input("PyGMT Map Title", value=config_svc.get("plotting.map_title", "Central Italy - Seismicity")).classes("w-80")
                grid_path = ui.input("GMT Grid Relief Path", value=config_svc.get("plotting.gmt_grid_path", "@earth_relief_15s")).classes("w-60")
                gmt_lib = ui.input("GMT Library Path (optional)", value=config_svc.get("plotting.gmt_library_path", "")).classes("w-60")
                log_fn = ui.input("GaMMA Log Filename", value=config_svc.get("analysis.log_filename", "picking_analysis.log")).classes("w-60")

                bind_val("plotting.map_title", mtitle, str)
                bind_val("plotting.gmt_grid_path", grid_path, str)
                bind_val("plotting.gmt_library_path", gmt_lib, str)
                bind_val("analysis.log_filename", log_fn, str)

            with ui.row().classes("seimlai-form-grid w-full gap-4 mt-2"):
                plot_region_raw = config_svc.get("plotting.region", [12.5, 14.00, 42.00, 43.50])
                plot_region_str = ", ".join(str(v) for v in plot_region_raw)
                plot_reg_in = ui.input("PyGMT Region [lon_min, lon_max, lat_min, lat_max]", value=plot_region_str).classes("seimlai-field-wide")
                bind_num_list("plotting.region", plot_reg_in, float)

                th_dpi = ui.number("Threshold Comparison Plot DPI", value=config_svc.get("threshold_analysis.dpi", 300), step=50).classes("w-60")
                bind_val("threshold_analysis.dpi", th_dpi, int)

        # Reuse the existing actions and callbacks in the sticky footer.
        actions.move(config_page)

    def refresh_fields():
        refreshing[0] = True
        try:
            for refresh in field_refreshers:
                refresh()
        finally:
            refreshing[0] = False
        update_map_rect()
        update_dirty()

    return lambda: bool(invalid_fields), refresh_fields
