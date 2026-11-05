"""Live Interactive Map page for SeiMLAI GUI.

Displays seismic stations and detected/located earthquakes on a near-full-screen
responsive Leaflet map with floating controls and real-time updates.
"""

from __future__ import annotations

import math
import re
from nicegui import app, ui
from seimlai.gui.components.basemaps import BASEMAPS
from seimlai.gui.services.catalog_watcher import CatalogWatcher, EarthquakeItem, StationItem
from seimlai.gui.services.config_service import ConfigService


DEPTH_COLORS = ("#ef4444", "#f97316", "#eab308", "#10b981", "#06b6d4", "#8b5cf6")
DEPTH_LABELS = ("< 5 km", "5-10 km", "10-15 km", "15-25 km", "25-40 km", "≥ 40 km")


def depth_color(depth_km: float, colors=DEPTH_COLORS) -> str:
    """Return the configured color for the event's depth interval."""
    for index, boundary in enumerate((5, 10, 15, 25, 40)):
        if depth_km < boundary:
            return colors[index]
    return colors[-1]


def create_live_map(watcher: CatalogWatcher, config_svc: ConfigService) -> None:
    """Render the near-full-screen interactive map page with floating HUD controls."""

    saved_colors = app.storage.user.get("depth_colors", list(DEPTH_COLORS))
    colors = list(saved_colors) if isinstance(saved_colors, list) and len(saved_colors) == 6 and all(isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in saved_colors) else list(DEPTH_COLORS)
    station_color = app.storage.user.get("station_color", "#2563eb")
    if not isinstance(station_color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", station_color):
        station_color = "#2563eb"
    station_color = [station_color]
    legend_dots = []

    # Inject custom Leaflet extensions for seismic triangle markers and tooltips
    ui.add_head_html("""
    <style>
    .station-triangle-marker {
        background: transparent !important;
        border: none !important;
    }
    </style>
    <script>
    (function() {
        function setupLeafletExtensions(leafletObj) {
            if (!leafletObj || leafletObj.triangleMarker) return;
            leafletObj.triangleMarker = function(latlng, options) {
                options = options || {};
                var size = options.size || 16;
                var fill = options.fillColor || '#2563eb';
                var stroke = options.color || '#1e3a8a';
                var weight = options.weight || 1.5;
                var opacity = options.opacity !== undefined ? options.opacity : 1.0;
                var fillOpacity = options.fillOpacity !== undefined ? options.fillOpacity : 0.9;
                var icon = leafletObj.divIcon({
                    className: 'station-triangle-marker',
                    html: '<svg width="' + size + '" height="' + size + '" viewBox="0 0 16 16" style="display:block; overflow:visible;">' +
                          '<polygon points="8,1 15,14 1,14" fill="' + fill + '" fill-opacity="' + fillOpacity + '" stroke="' + stroke + '" stroke-width="' + weight + '" stroke-opacity="' + opacity + '" stroke-linejoin="round"/>' +
                          '</svg>',
                    iconSize: [size, size],
                    iconAnchor: [size / 2, size / 2],
                    tooltipAnchor: [0, -size / 2]
                });
                var marker = leafletObj.marker(latlng, { icon: icon });
                if (options.tooltip) {
                    marker.bindTooltip(options.tooltip);
                }
                return marker;
            };

            leafletObj.seismicEvents = function(events) {
                var renderer = leafletObj.canvas();
                return leafletObj.layerGroup(events.map(function(event) {
                    return leafletObj.circleMarker(event.latlng, {
                        radius: event.radius,
                        fillColor: event.color,
                        color: '#0f172a',
                        weight: 1.2,
                        opacity: 0.9,
                        fillOpacity: 0.75,
                        renderer: renderer
                    }).bindTooltip(event.tooltip);
                }));
            };

            var origCircleMarker = leafletObj.circleMarker;
            if (origCircleMarker && !origCircleMarker._hasTooltipPatch) {
                leafletObj.circleMarker = function(latlng, options) {
                    var cm = origCircleMarker.call(leafletObj, latlng, options);
                    if (options && options.tooltip) {
                        cm.bindTooltip(options.tooltip);
                    }
                    return cm;
                };
                leafletObj.circleMarker._hasTooltipPatch = true;
            }
        }

        if (window.L) {
            setupLeafletExtensions(window.L);
        }
        var currentL = window.L;
        try {
            Object.defineProperty(window, 'L', {
                configurable: true,
                enumerable: true,
                get: function() { return currentL; },
                set: function(val) {
                    currentL = val;
                    setupLeafletExtensions(val);
                }
            });
        } catch(e) {}
    })();
    </script>
    """)

    def station_symbol(color):
        return (
            '<svg width="13" height="13" viewBox="0 0 16 16" style="display:inline-block; vertical-align:middle;">'
            f'<polygon points="8,1 15,14 1,14" fill="{color}" stroke="#1e3a8a" stroke-width="1.5" stroke-linejoin="round"/>'
            '</svg>'
        )

    # Compute initial bounding box & center
    geo = config_svc.get("geography", {})
    minlat = float(geo.get("minlatitude", 42.25))
    maxlat = float(geo.get("maxlatitude", 43.12))
    minlon = float(geo.get("minlongitude", 11.75))
    maxlon = float(geo.get("maxlongitude", 14.00))

    center_lat = (minlat + maxlat) / 2.0
    center_lon = (minlon + maxlon) / 2.0

    # Main full-height map container
    with ui.element("div").classes(
        "seimlai-live-map w-full relative h-[calc(100vh-140px)] min-h-[620px] overflow-hidden"
    ):

        # 1. Full-screen Leaflet Map
        leaflet_map = ui.leaflet(center=(center_lat, center_lon), zoom=8).classes("w-full h-full")

        # 2. Top Floating HUD (Glassmorphism toolbar)
        with ui.row().classes("seimlai-map-toolbar"):
            # Left HUD: Title & Catalog selector
            with ui.row().classes("seimlai-map-overlay seimlai-map-controls items-center gap-2"):
                ui.icon("sym_o_layers").classes("text-primary text-xl")

                catalog_select = ui.select(
                    {
                        "gamma": "GaMMA (Raw)",
                        "hypoellipse": "HypoEllipse (1D)",
                        "hypodd": "HypoDD (Relocated)",
                    },
                    value=watcher.active_source,
                    label="Catalog",
                ).props("dense outlined").classes("seimlai-map-catalog")

                basemap_select = ui.select(
                    {k: v["name"] for k, v in BASEMAPS.items()},
                    value="osm",
                    label="Basemap",
                ).props("dense outlined").classes("seimlai-map-basemap")

                refresh_btn = ui.button(icon="sym_o_refresh").props('flat dense round color=secondary aria-label="Refresh map data"').tooltip("Refresh data")

            # Right HUD: Badges
            with ui.row().classes("seimlai-map-overlay seimlai-map-summary items-center gap-2"):
                sta_count_badge = ui.badge(f"Stations: {len(watcher.stations)}", color="secondary").classes("text-xs font-mono")
                eq_count_badge = ui.badge(f"Events: {len(watcher.get_active_catalog())}", color="secondary").classes("text-xs font-mono")


        # 3. Bottom Floating Legend HUD
        with ui.row().classes(
            "seimlai-map-overlay seimlai-map-legend items-center gap-3"
        ).props('role=group aria-label="Earthquake depth legend"'):
            ui.label("Depth").classes("font-semibold")
            for index, label in enumerate(DEPTH_LABELS):
                with ui.row().classes("items-center gap-1"):
                    legend_dots.append(ui.element("span").props("aria-hidden=true").style(f"background-color: {colors[index]}").classes("seimlai-depth-dot"))
                    ui.label(label)

            with ui.button(icon="sym_o_palette").props('flat dense round color=secondary aria-label="Change map colors"').tooltip("Change map colors"):
                with ui.menu():
                    with ui.column().classes("p-3 gap-2"):
                        ui.label("Map colors").classes("font-semibold")
                        for index, label in enumerate(DEPTH_LABELS):
                            def change_color(e, index=index):
                                if isinstance(e.value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", e.value):
                                    colors[index] = e.value
                                    app.storage.user["depth_colors"] = list(colors)
                                    legend_dots[index].style(f"background-color: {e.value}")
                                    draw_map_elements()
                            ui.color_input(label, value=colors[index], on_change=change_color, preview=True).props("dense outlined")
                        def change_station_color(e):
                            if isinstance(e.value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", e.value):
                                station_color[0] = e.value
                                app.storage.user["station_color"] = e.value
                                station_icon.content = station_symbol(e.value)
                                draw_map_elements()
                        ui.color_input("Stations", value=station_color[0], on_change=change_station_color, preview=True).props("dense outlined")

            ui.separator().props("vertical").classes("mx-1")
            with ui.row().classes("items-center gap-1.5"):
                station_icon = ui.html(station_symbol(station_color[0]))
                ui.label("Stations (triangle)")

    # 4. Map Drawing Logic
    def draw_map_elements():
        """Redraw all map elements (bounding box, stations, and earthquakes)."""
        leaflet_map.clear_layers()

        # Dynamic selected basemap tile layer
        bmap = BASEMAPS.get(basemap_select.value, BASEMAPS["osm"])
        leaflet_map.tile_layer(
            url_template=bmap["url"],
            options={"attribution": bmap["attribution"], "maxZoom": bmap["max_zoom"]},
        )

        # Configured Bounding Box
        geo = config_svc.get("geography", {})
        leaflet_map.generic_layer(
            name="rectangle",
            args=[
                [[float(geo.get("minlatitude", 42.25)), float(geo.get("minlongitude", 11.75))],
                 [float(geo.get("maxlatitude", 43.12)), float(geo.get("maxlongitude", 14.00))]],
                {"color": "#3b82f6", "weight": 2, "dashArray": "5, 5", "fill": False},
            ],
        )

        # Draw stations as triangles (standard seismological station symbol)
        for sta in watcher.stations:
            tip = f"<b>Station:</b> {sta.network}.{sta.station}<br>Lat: {sta.latitude:.4f}, Lon: {sta.longitude:.4f}"
            if sta.elevation is not None:
                tip += f"<br>Elevation: {sta.elevation} m"

            s_layer = leaflet_map.generic_layer(
                name="triangleMarker",
                args=[
                    [sta.latitude, sta.longitude],
                    {
                        "size": 16,
                        "fillColor": station_color[0],
                        "color": "#1e3a8a",
                        "weight": 1.5,
                        "opacity": 1.0,
                        "fillOpacity": 0.9,
                        "tooltip": tip,
                    },
                ],
            )
            s_layer.run_method("bindTooltip", tip)

        # Draw earthquakes for active catalog
        catalog = watcher.get_active_catalog()
        sta_count_badge.text = f"Stations: {len(watcher.stations)}"
        eq_count_badge.text = f"Events: {len(catalog)}"

        events = []
        for eq in catalog:
            color = depth_color(eq.depth_km, colors)
            radius = 5.0
            if eq.magnitude is not None and not math.isnan(eq.magnitude):
                radius = max(3.5, min(20.0, float(eq.magnitude) * 4.0))

            tip = f"<b>Event #{eq.id}</b> ({eq.source.upper()})<br>"
            if eq.time_str:
                tip += f"Time: {eq.time_str}<br>"
            tip += f"Lat: {eq.latitude:.4f}, Lon: {eq.longitude:.4f}<br>"
            tip += f"Depth: {eq.depth_km:.1f} km<br>"
            if eq.magnitude is not None:
                tip += f"Magnitude: M{eq.magnitude:.1f}"

            events.append({
                "latlng": [eq.latitude, eq.longitude],
                "radius": radius,
                "color": color,
                "tooltip": tip,
            })

        leaflet_map.generic_layer(name="seismicEvents", args=[events])

        # Trigger leaflet resize to ensure full-screen tiles are sharp
        leaflet_map.run_map_method("invalidateSize")

    def on_catalog_select(e):
        watcher.active_source = e.value
        draw_map_elements()

    def on_watcher_event(event_type: str, items: list):
        draw_map_elements()

    catalog_select.on_value_change(on_catalog_select)
    basemap_select.on_value_change(lambda: draw_map_elements())
    refresh_btn.on("click", lambda: (watcher.refresh(), draw_map_elements()))

    # Watcher listener & render on init
    watcher.add_listener(on_watcher_event)
    config_svc.add_change_listener(lambda key, value: draw_map_elements() if key in (
        "geography.minlatitude", "geography.maxlatitude",
        "geography.minlongitude", "geography.maxlongitude",
    ) else None)
    leaflet_map.on("init", draw_map_elements)
    draw_map_elements()
