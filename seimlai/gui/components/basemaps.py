"""Basemap definitions and tile layer configurations for SeiMLAI Leaflet maps."""

from __future__ import annotations

BASEMAPS: dict[str, dict] = {
    "osm": {
        "name": "OpenStreetMap",
        "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "© OpenStreetMap contributors",
        "max_zoom": 19,
    },
    "satellite": {
        "name": "Satellite (Esri)",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Tiles © Esri",
        "max_zoom": 19,
    },
    "topo": {
        "name": "Topographic (OpenTopo)",
        "url": "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        "attribution": "© OpenStreetMap contributors, SRTM | © OpenTopoMap",
        "max_zoom": 17,
    },
    "esri_topo": {
        "name": "Esri World Topo",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Tiles © Esri",
        "max_zoom": 19,
    },
}

