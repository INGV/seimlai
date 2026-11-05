import { useEffect, useRef, useState } from "react";
import {
  Viewer,
  Cartesian2,
  Cartesian3,
  Color,
  Rectangle,
  Math as CesiumMath,
  UrlTemplateImageryProvider,
  PointPrimitiveCollection,
  BillboardCollection,
  NearFarScalar,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  Cartographic,
  EllipsoidTerrainProvider,
  ArcType,
  BoundingSphere,
  HeadingPitchRange,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import {
  api,
  type Catalog,
  type Earthquake,
  type Station,
  type Value,
} from "./api";

const defaults = [
  "#ef4444",
  "#f97316",
  "#eab308",
  "#10b981",
  "#06b6d4",
  "#8b5cf6",
];
const depthLabels = ["< 5", "5–10", "10–15", "15–25", "25–40", "≥ 40"];
const basemaps = {
  osm: {
    label: "OpenStreetMap",
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    credit: "© OpenStreetMap contributors",
    max: 19,
  },
  satellite: {
    label: "Satellite · Esri",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    credit: "Tiles © Esri",
    max: 19,
  },
  topo: {
    label: "OpenTopoMap",
    url: "https://tile.opentopomap.org/{z}/{x}/{y}.png",
    credit: "© OpenStreetMap contributors, SRTM | © OpenTopoMap",
    max: 17,
  },
  esri_topo: {
    label: "Esri World Topo",
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    credit: "Tiles © Esri",
    max: 19,
  },
};
type Bounds = {
  minlatitude: number;
  maxlatitude: number;
  minlongitude: number;
  maxlongitude: number;
};

export default function SeismicMap({
  geography,
  revision,
  preview = false,
  onBounds,
}: {
  geography: Record<string, Value>;
  revision?: number;
  preview?: boolean;
  onBounds?: (bounds: Bounds) => void;
}) {
  const host = useRef<HTMLDivElement>(null),
    viewer = useRef<Viewer | null>(null);
  const eventPoints = useRef<PointPrimitiveCollection | null>(null),
    stationPoints = useRef<BillboardCollection | null>(null);
  const [source, setSource] = useState("gamma"),
    [basemap, setBasemap] = useState<keyof typeof basemaps>("osm");
  const [opacity, setOpacity] = useState(0.35),
    [underground, setUnderground] = useState(true);
  const [offset, setOffset] = useState(0),
    [colors, setColors] = useState(() => {
      try {
        const saved = JSON.parse(
          localStorage.getItem("seimlai-depth-colors") ?? "null",
        );
        return Array.isArray(saved) &&
          saved.length === 6 &&
          saved.every((c) => typeof c === "string" && /^#[0-9a-f]{6}$/i.test(c))
          ? (saved as string[])
          : defaults;
      } catch {
        return defaults;
      }
    });
  const [stationColor, setStationColor] = useState("#2563eb");
  const [catalog, setCatalog] = useState<Catalog>({ events: [], stations: [] }),
    [error, setError] = useState("");
  const [ready, setReady] = useState(false),
    [loading, setLoading] = useState(false),
    [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<Earthquake | Station | null>(null);
  const [drawing, setDrawing] = useState(false),
    [first, setFirst] = useState<Cartographic | null>(null);
  const onBoundsRef = useRef(onBounds);
  onBoundsRef.current = onBounds;
  const geo = Object.fromEntries(
    ["minlatitude", "maxlatitude", "minlongitude", "maxlongitude"].map((k) => [
      k,
      Number(geography[k]),
    ]),
  ) as Bounds;
  const geoKey = JSON.stringify(geo);
  const validBounds =
    Object.values(geo).every(Number.isFinite) &&
    geo.minlatitude < geo.maxlatitude &&
    geo.minlongitude < geo.maxlongitude &&
    geo.minlatitude >= -90 &&
    geo.maxlatitude <= 90 &&
    geo.minlongitude >= -180 &&
    geo.maxlongitude <= 180;

  function fit() {
    if (!validBounds) return;
    viewer.current?.camera.flyTo({
      destination: Rectangle.fromDegrees(
        geo.minlongitude,
        geo.minlatitude,
        geo.maxlongitude,
        geo.maxlatitude,
      ),
      duration: 0.8,
    });
  }

  function depthView() {
    const positions = catalog.events
      .filter((event) => event.depth_km !== null && Number.isFinite(event.depth_km) && Number.isFinite(event.latitude) && Number.isFinite(event.longitude))
      .map((event) => Cartesian3.fromDegrees(event.longitude, event.latitude, offset - event.depth_km! * 1000));
    if (!positions.length || !viewer.current) return;
    const sphere = BoundingSphere.fromPoints(positions);
    setUnderground(true);
    viewer.current.camera.flyToBoundingSphere(sphere, {
      offset: new HeadingPitchRange(0, CesiumMath.toRadians(-20), Math.max(sphere.radius * 2.8, 20000)),
      duration: matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 0.8,
    });
  }

  useEffect(() => {
    let v: Viewer;
    try {
      v = new Viewer(host.current!, {
        baseLayer: false,
        terrainProvider: new EllipsoidTerrainProvider(),
        animation: false,
        timeline: false,
        baseLayerPicker: false,
        geocoder: false,
        homeButton: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        fullscreenButton: false,
        infoBox: false,
        selectionIndicator: false,
        requestRenderMode: true,
      });
    } catch (problem) {
      setError(`3D viewer could not start: ${String(problem)}`);
      return;
    }
    viewer.current = v;
    v.scene.globe.baseColor = Color.fromCssColorString("#173343");
    v.scene.globe.depthTestAgainstTerrain = true;
    eventPoints.current = v.scene.primitives.add(
      new PointPrimitiveCollection(),
    );
    stationPoints.current = v.scene.primitives.add(new BillboardCollection());
    const events = new ScreenSpaceEventHandler(v.scene.canvas);
    events.setInputAction((event: { position: Cartesian2 }) => {
      const hit = v.scene.pick(event.position);
      setSelected(
        hit?.id?.kind === "earthquake" || hit?.id?.kind === "station"
          ? hit.id.data
          : null,
      );
    }, ScreenSpaceEventType.LEFT_CLICK);
    const resize = new ResizeObserver(() => {
      v.resize();
      v.scene.requestRender();
    });
    resize.observe(host.current!);
    setReady(true);
    return () => {
      setReady(false);
      resize.disconnect();
      events.destroy();
      viewer.current = null;
      v.destroy();
    };
  }, []);

  useEffect(() => {
    if (preview) return;
    let active = true;
    setLoading(true);
    setSelected(null);
    setCatalog({ events: [], stations: [] });
    api<Catalog>(`/catalogs/${source}`)
      .then((data) => {
        if (active) {
          setCatalog(data);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(String(e.message));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [source, revision, preview, refresh]);

  useEffect(() => {
    if (!viewer.current || !ready) return;
    const v = viewer.current,
      provider = basemaps[basemap];
    v.imageryLayers.removeAll();
    const imagery = new UrlTemplateImageryProvider({
      url: provider.url,
      credit: provider.credit,
      maximumLevel: provider.max,
    });
    const removeError = imagery.errorEvent.addEventListener(() =>
      setError(
        "Basemap tiles could not be loaded. Check the connection or choose another basemap.",
      ),
    );
    v.imageryLayers.addImageryProvider(imagery);
    v.scene.requestRender();
    return removeError;
  }, [ready, basemap]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !ready) return;
    v.scene.globe.translucency.enabled = !preview && underground;
    v.scene.globe.translucency.frontFaceAlpha = opacity;
    v.scene.globe.translucency.backFaceAlpha = opacity;
    v.scene.screenSpaceCameraController.enableCollisionDetection =
      preview || !underground;
    v.scene.requestRender();
  }, [ready, underground, opacity, preview]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !ready || !validBounds) return;
    const existing = v.entities.getById("bounds");
    if (existing) v.entities.remove(existing);
    v.entities.add({
      id: "bounds",
      polyline: {
        positions: Cartesian3.fromDegreesArray([
          geo.minlongitude,
          geo.minlatitude,
          geo.maxlongitude,
          geo.minlatitude,
          geo.maxlongitude,
          geo.maxlatitude,
          geo.minlongitude,
          geo.maxlatitude,
          geo.minlongitude,
          geo.minlatitude,
        ]),
        width: 2,
        material: Color.fromCssColorString("#4e9fff"),
        arcType: ArcType.GEODESIC,
      },
    });
    v.camera.setView({
      destination: Rectangle.fromDegrees(
        geo.minlongitude,
        geo.minlatitude,
        geo.maxlongitude,
        geo.maxlatitude,
      ),
    });
    v.scene.requestRender();
  }, [ready, geoKey, validBounds]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !ready) return;
    const points = eventPoints.current!,
      stations = stationPoints.current!;
    points.removeAll();
    stations.removeAll();
    catalog.events.forEach((eq) => {
      if (
        eq.depth_km === null ||
        !Number.isFinite(eq.depth_km) ||
        !Number.isFinite(eq.latitude) ||
        !Number.isFinite(eq.longitude)
      )
        return;
      const index = [5, 10, 15, 25, 40].findIndex((b) => eq.depth_km! < b);
      points.add({
        position: Cartesian3.fromDegrees(
          eq.longitude,
          eq.latitude,
          offset - eq.depth_km * 1000,
        ),
        color: Color.fromCssColorString(colors[index < 0 ? 5 : index]),
        pixelSize:
          eq.magnitude === null
            ? 7
            : Math.max(5, Math.min(24, eq.magnitude * 4)),
        outlineColor: Color.fromCssColorString("#172333"),
        outlineWidth: 1,
        id: { kind: "earthquake", data: eq },
      });
    });
    const image = `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><path d="M10 2L18 17H2Z" fill="${stationColor}" stroke="#e0e9f0" stroke-width="1.3"/></svg>`)}`;
    catalog.stations.forEach((sta) => {
      if (!Number.isFinite(sta.latitude) || !Number.isFinite(sta.longitude))
        return;
      stations.add({
        position: Cartesian3.fromDegrees(
          sta.longitude,
          sta.latitude,
          sta.elevation ?? 0,
        ),
        image,
        width: 18,
        height: 18,
        scaleByDistance: new NearFarScalar(1000, 1.2, 10000000, 0.6),
        id: { kind: "station", data: sta },
      });
    });
    localStorage.setItem("seimlai-depth-colors", JSON.stringify(colors));
    v.scene.requestRender();
  }, [ready, catalog, colors, stationColor, offset]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || !drawing) return;
    const handler = new ScreenSpaceEventHandler(v.scene.canvas);
    handler.setInputAction((event: { position: Cartesian2 }) => {
      const point = v.camera.pickEllipsoid(
        event.position,
        v.scene.globe.ellipsoid,
      );
      if (!point) return;
      const cartographic = Cartographic.fromCartesian(point);
      if (!first) {
        setFirst(cartographic);
        return;
      }
      onBoundsRef.current?.({
        minlatitude: CesiumMath.toDegrees(
          Math.min(first.latitude, cartographic.latitude),
        ),
        maxlatitude: CesiumMath.toDegrees(
          Math.max(first.latitude, cartographic.latitude),
        ),
        minlongitude: CesiumMath.toDegrees(
          Math.min(first.longitude, cartographic.longitude),
        ),
        maxlongitude: CesiumMath.toDegrees(
          Math.max(first.longitude, cartographic.longitude),
        ),
      });
      setDrawing(false);
      setFirst(null);
    }, ScreenSpaceEventType.LEFT_CLICK);
    return () => handler.destroy();
  }, [drawing, first]);

  async function reload() {
    setLoading(true);
    try {
      await api("/catalogs/refresh", "POST");
      setRefresh((x) => x + 1);
    } catch (e) {
      setError(String(e));
      setLoading(false);
    }
  }
  return (
    <section
      className={`seismic-map ${preview ? "map-preview" : ""}`}
      aria-label={preview ? "Geographic bounds preview" : "Live 3D seismic map"}
    >
      <div ref={host} className="cesium-host" />
      <div className="map-top">
        <div className="map-overlay map-toolbar">
          {!preview && (
            <>
              <span className="map-symbol">◎</span>
              <select
                aria-label="Earthquake catalog"
                value={source}
                onChange={(e) => setSource(e.target.value)}
              >
                <option value="gamma">GaMMA</option>
                <option value="hypoellipse">HypoEllipse</option>
                <option value="hypodd">HypoDD</option>
              </select>
            </>
          )}
          <select
            aria-label="Basemap"
            value={basemap}
            onChange={(e) =>
              setBasemap(e.target.value as keyof typeof basemaps)
            }
          >
            {Object.entries(basemaps).map(([key, map]) => (
              <option key={key} value={key}>
                {map.label}
              </option>
            ))}
          </select>
          <button onClick={fit} disabled={!ready || !validBounds}>
            Fit area
          </button>
          {!preview && <button onClick={depthView} disabled={!ready || !catalog.events.length}>Depth view</button>}
          {preview ? (
            <button
              onClick={() => {
                setDrawing((x) => !x);
                setFirst(null);
              }}
            >
              {drawing ? "Cancel selection" : "Draw bounds"}
            </button>
          ) : (
            <button onClick={reload} disabled={loading}>
              ↻ Refresh
            </button>
          )}
        </div>
        {!preview && (
          <div className="map-overlay map-counts">
            {loading
              ? "Updating…"
              : `${catalog.stations.length} stations · ${catalog.events.length} events`}
          </div>
        )}
      </div>
      {drawing && (
        <div className="map-overlay draw-instructions">
          {first
            ? "Click the opposite corner."
            : "Click the first corner of the study area."}
        </div>
      )}
      {!validBounds && (
        <div className="map-overlay map-error">
          Enter valid geographic bounds to preview the study area.
        </div>
      )}
      {error && (
        <div className="map-overlay map-error" role="alert">
          {error}
          <button aria-label="Dismiss map error" onClick={() => setError("")}>
            ×
          </button>
        </div>
      )}
      {!preview && (
        <>
          <aside className="map-overlay subsurface-controls">
            <span className="eyebrow">SUBSURFACE VIEW</span>
            <label className="inline-field">
              <input
                type="checkbox"
                checked={underground}
                onChange={(e) => setUnderground(e.target.checked)}
              />{" "}
              See underground
            </label>
            <label>
              Surface opacity <span>{Math.round(opacity * 100)}%</span>
              <input
                aria-label="Surface opacity"
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={opacity}
                onChange={(e) => setOpacity(Number(e.target.value))}
                disabled={!underground}
              />
            </label>
            <details>
              <summary>Depth reference & colors</summary>
              <label>
                Catalog zero → ellipsoid (m)
                <input
                  aria-label="Vertical datum offset in meters"
                  type="number"
                  value={offset}
                  onChange={(e) => {
                    if (Number.isFinite(e.target.valueAsNumber))
                      setOffset(e.target.valueAsNumber);
                  }}
                />
              </label>
              <p>
                Display height = offset − depth × 1000. Zero assumes catalog
                depth is measured from the ellipsoid. Adjust for the catalog
                datum; no geoid correction is applied.
              </p>
              <p>
                Stations use reported elevation as ellipsoid height. Terrain is
                an ellipsoid, without topographic relief.
              </p>
              {colors.map((c, i) => (
                <label className="color-field" key={i}>
                  {depthLabels[i]} km
                  <input
                    type="color"
                    aria-label={`Depth color ${depthLabels[i]} km`}
                    value={c}
                    onChange={(e) =>
                      setColors((previous) =>
                        previous.map((v, j) => (i === j ? e.target.value : v)),
                      )
                    }
                  />
                </label>
              ))}
              <label className="color-field">
                Stations
                <input
                  type="color"
                  value={stationColor}
                  onChange={(e) => setStationColor(e.target.value)}
                />
              </label>
            </details>
            <p className="map-hint">
              Drag to pan · Wheel to zoom
              <br />
              Ctrl + drag to tilt · Click a point for details
            </p>
          </aside>
          {!loading && !catalog.events.length && !error && (
            <div className="map-overlay empty-catalog">
              No events in this catalog yet. Run the pipeline or choose another
              catalog.
            </div>
          )}
          <div className="map-overlay map-legend">
            <strong>Depth · km</strong>
            {colors.map((c, i) => (
              <span key={i}>
                <i style={{ backgroundColor: c }} />
                {depthLabels[i]}
              </span>
            ))}
            <span>
              <b style={{ color: stationColor }}>▲</b> Stations
            </span>
          </div>
          {selected && (
            <aside className="map-overlay point-details">
              <button
                className="close-details"
                aria-label="Close point details"
                onClick={() => setSelected(null)}
              >
                ×
              </button>
              {"depth_km" in selected ? (
                <>
                  <span className="eyebrow">
                    {selected.source.toUpperCase()} EVENT
                  </span>
                  <h3>#{selected.id}</h3>
                  <p>{selected.time_str || "Time unavailable"}</p>
                  <dl>
                    <dt>Depth</dt>
                    <dd>{selected.depth_km?.toFixed(2) ?? "—"} km</dd>
                    <dt>Magnitude</dt>
                    <dd>{selected.magnitude?.toFixed(1) ?? "—"}</dd>
                  </dl>
                </>
              ) : (
                <>
                  <span className="eyebrow">SEISMIC STATION</span>
                  <h3>
                    {selected.network}.{selected.station}
                  </h3>
                  <p>Elevation: {selected.elevation ?? "—"} m</p>
                </>
              )}
              <p>
                {selected.latitude.toFixed(4)}° N ·{" "}
                {selected.longitude.toFixed(4)}° E
              </p>
            </aside>
          )}
        </>
      )}
    </section>
  );
}
