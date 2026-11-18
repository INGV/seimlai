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
  EllipsoidalOccluder,
  SceneMode,
  CameraEventAggregator,
  CameraEventType,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";
import CesiumNavigation from "cesium-navigation-es6";
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
  const surfaceMarkers = useRef<Array<{ position: Cartesian3; show: boolean }>>([]);
  const minimapHost = useRef<HTMLDivElement>(null),
    cameraArrow = useRef<SVGSVGElement>(null);
  const pitchArrow = useRef<SVGGElement>(null),
    pitchLabel = useRef<HTMLSpanElement>(null);
  const minimap = useRef<Viewer | null>(null),
    minimapWidth = useRef(100000);
  const [underground, setUnderground] = useState(false);
  const [source, setSource] = useState("gamma"),
    [basemap, setBasemap] = useState<keyof typeof basemaps>("osm");
  const [opacity, setOpacity] = useState(0.35);
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
  const [surfaceEvents, setSurfaceEvents] = useState(false);
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

  function zoomMinimap(factor: number) {
    if (!minimap.current || !viewer.current) return;
    minimapWidth.current = Math.max(1000, Math.min(40000000, minimapWidth.current * factor));
    const position = viewer.current.camera.positionCartographic;
    minimap.current.camera.setView({
      destination: Cartesian3.fromRadians(position.longitude, position.latitude, minimapWidth.current),
    });
    minimap.current.scene.requestRender();
  }

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
        fullscreenButton: preview,
        fullscreenElement: host.current!.parentElement!,
        infoBox: false,
        selectionIndicator: false,
        requestRenderMode: true,
      });
    } catch (problem) {
      setError(`3D viewer could not start: ${String(problem)}`);
      return;
    }
    viewer.current = v;
    // Surface markers use an artificial depth; camera navigation must pick the globe instead.
    v.scene.useDepthPicking = preview;
    // The package's declarations omit its public destroy method.
    const navigation = preview ? null : new CesiumNavigation(v, {
      enableCompass: true,
      enableCompassOuterRing: true,
      enableZoomControls: true,
      enableDistanceLegend: true,
    }) as CesiumNavigation & { destroy(): void };
    const zoomInput = preview ? null : new CameraEventAggregator(v.scene.canvas);
    const zoom = (distance: number) => {
      v.camera.moveForward(distance);
      v.scene.requestRender();
    };
    if (!preview) v.scene.screenSpaceCameraController.enableZoom = false;
    const removeZoom = zoomInput ? v.scene.preUpdate.addEventListener(() => {
      for (const type of [CameraEventType.WHEEL, CameraEventType.RIGHT_DRAG, CameraEventType.PINCH]) {
        if (!zoomInput.isMoving(type)) continue;
        const movement = zoomInput.getMovement(type);
        const positions = type === CameraEventType.PINCH ? movement.distance : movement;
        // Wheel deltas are radians × 7.5; pinch distances are quarter-pixels in Cesium.
        const metersPerUnit = type === CameraEventType.WHEEL ? 1000 / (5 * Math.PI) : type === CameraEventType.PINCH ? 40 : 10;
        zoom((positions.endPosition.y - positions.startPosition.y) * metersPerUnit);
      }
      zoomInput.reset();
    }) : null;
    const onZoomClick = (event: Event) => {
      if (preview || !(event.target instanceof Element)) return;
      const control = event.target.closest(".navigation-control, .navigation-control-last");
      const zoomIn = control?.querySelector(".navigation-control-icon-zoom-in");
      const zoomOut = control?.querySelector(".navigation-control-icon-zoom-out");
      if (!zoomIn && !zoomOut) return;
      event.stopImmediatePropagation();
      event.preventDefault();
      zoom(zoomIn ? 1000 : -1000);
    };
    v.container.addEventListener("click", onZoomClick, true);
    const outerRing = v.container.querySelector<SVGPathElement>(".compass-outer-ring svg path");
    if (outerRing) {
      // The plugin's default ring path starts with the N; overlay only that subpath.
      const north = outerRing.cloneNode(false) as SVGPathElement;
      north.setAttribute("d", outerRing.getAttribute("d")!.split(/z/i)[0] + "z");
      north.style.fill = "var(--accent)";
      north.style.stroke = "#172333";
      north.style.strokeWidth = "1.5";
      north.style.paintOrder = "stroke";
      outerRing.parentNode!.appendChild(north);
    }
    v.scene.globe.baseColor = Color.fromCssColorString("#173343");
    v.scene.globe.depthTestAgainstTerrain = true;
    eventPoints.current = v.scene.primitives.add(
      new PointPrimitiveCollection(),
    );
    stationPoints.current = v.scene.primitives.add(new BillboardCollection());
    const occluder = new EllipsoidalOccluder(v.scene.globe.ellipsoid);
    const removeSurfaceVisibility = v.scene.preRender.addEventListener(() => {
      occluder.cameraPosition = v.camera.positionWC;
      const occlude = v.scene.globe.translucency.frontFaceAlpha === 1 && !v.scene.cameraUnderground;
      for (const marker of surfaceMarkers.current) {
        marker.show = !occlude || occluder.isPointVisible(marker.position);
      }
    });
    let wasUnderground = false;
    const removeUndergroundVisibility = v.scene.postRender.addEventListener(() => {
      const belowSurface = !preview && v.scene.cameraUnderground;
      if (belowSurface !== wasUnderground) {
        wasUnderground = belowSurface;
        setUnderground(belowSurface);
      }
    });
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
      removeSurfaceVisibility();
      removeUndergroundVisibility();
      surfaceMarkers.current = [];
      removeZoom?.();
      zoomInput?.destroy();
      v.container.removeEventListener("click", onZoomClick, true);
      navigation?.destroy();
      viewer.current = null;
      v.destroy();
    };
  }, []);

  useEffect(() => {
    const main = viewer.current;
    if (preview || !ready || !underground || !main || !minimapHost.current) return;
    let mini: Viewer;
    try {
      mini = new Viewer(minimapHost.current, {
        baseLayer: false,
        terrainProvider: new EllipsoidTerrainProvider(),
        sceneMode: SceneMode.SCENE2D,
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
      setError(`Orientation map could not start: ${String(problem)}`);
      return;
    }
    minimap.current = mini;
    mini.scene.screenSpaceCameraController.enableInputs = false;
    const container = minimapHost.current;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();
      zoomMinimap(Math.exp(Math.max(-1, Math.min(1, event.deltaY * 0.002))));
    };
    container.addEventListener("wheel", onWheel, { passive: false });
    const provider = basemaps[basemap];
    const imagery = new UrlTemplateImageryProvider({
      url: provider.url,
      credit: provider.credit,
      maximumLevel: provider.max,
    });
    const removeError = imagery.errorEvent.addEventListener(() =>
      setError("Orientation map tiles could not be loaded. Check the connection or choose another basemap."),
    );
    mini.imageryLayers.addImageryProvider(imagery);
    let longitude: number | undefined, latitude: number | undefined;
    const syncCamera = () => {
      const position = main.camera.positionCartographic;
      if (position.longitude !== longitude || position.latitude !== latitude) {
        longitude = position.longitude;
        latitude = position.latitude;
        // In 2D the destination height sets the map width; preserve the user's zoom while following.
        mini.camera.setView({
          destination: Cartesian3.fromRadians(longitude, latitude, minimapWidth.current),
        });
        mini.scene.requestRender();
      }
      if (cameraArrow.current) {
        cameraArrow.current.style.transform = `rotate(${main.camera.heading}rad)`;
      }
      const pitch = CesiumMath.toDegrees(main.camera.pitch);
      if (pitchArrow.current) {
        // SVG's vertical axis points down; negate pitch so upward views point up.
        pitchArrow.current.setAttribute("transform", `rotate(${-pitch} 24 24)`);
      }
      if (pitchLabel.current) {
        pitchLabel.current.textContent = `Pitch ${Math.round(pitch)}°`;
      }
    };
    syncCamera();
    const removeSync = main.scene.postRender.addEventListener(syncCamera);
    const resize = new ResizeObserver(() => {
      mini.resize();
      longitude = undefined;
      syncCamera();
      mini.scene.requestRender();
    });
    resize.observe(minimapHost.current);
    return () => {
      resize.disconnect();
      removeSync();
      removeError();
      container.removeEventListener("wheel", onWheel);
      minimap.current = null;
      mini.destroy();
    };
  }, [preview, ready, underground, basemap]);

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
    v.scene.globe.depthTestAgainstTerrain = !surfaceEvents;
    v.scene.globe.translucency.enabled = !preview;
    v.scene.globe.translucency.frontFaceAlpha = opacity;
    v.scene.globe.translucency.backFaceAlpha = opacity;
    v.scene.screenSpaceCameraController.enableCollisionDetection =
      preview;
    v.scene.requestRender();
  }, [ready, opacity, preview, surfaceEvents]);

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
    surfaceMarkers.current = [];
    catalog.events.forEach((eq) => {
      if (
        eq.depth_km === null ||
        !Number.isFinite(eq.depth_km) ||
        !Number.isFinite(eq.latitude) ||
        !Number.isFinite(eq.longitude)
      )
        return;
      const index = [5, 10, 15, 25, 40].findIndex((b) => eq.depth_km! < b);
      const height = surfaceEvents ? 0 : offset - eq.depth_km * 1000;
      const point = points.add({
        position: Cartesian3.fromDegrees(
          eq.longitude,
          eq.latitude,
          height,
        ),
        color: Color.fromCssColorString(colors[index < 0 ? 5 : index]),
        pixelSize:
          eq.magnitude === null
            ? 7
            : Math.max(5, Math.min(24, eq.magnitude * 4)),
        outlineColor: Color.fromCssColorString("#172333"),
        outlineWidth: 1,
        // Surface symbols must not be clipped; preRender handles opaque-globe occlusion.
        disableDepthTestDistance: height >= 0 ? Number.POSITIVE_INFINITY : 0,
        id: { kind: "earthquake", data: eq },
      });
      if (height >= 0) surfaceMarkers.current.push(point);
    });
    const image = `data:image/svg+xml,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><path d="M10 2L18 17H2Z" fill="${stationColor}" stroke="#e0e9f0" stroke-width="1.3"/></svg>`)}`;
    catalog.stations.forEach((sta) => {
      if (!Number.isFinite(sta.latitude) || !Number.isFinite(sta.longitude))
        return;
      const height = sta.elevation ?? 0;
      const station = stations.add({
        position: Cartesian3.fromDegrees(
          sta.longitude,
          sta.latitude,
          height,
        ),
        image,
        width: 18,
        height: 18,
        disableDepthTestDistance: height >= 0 ? Number.POSITIVE_INFINITY : 0,
        scaleByDistance: new NearFarScalar(1000, 1.2, 10000000, 0.6),
        id: { kind: "station", data: sta },
      });
      if (height >= 0) surfaceMarkers.current.push(station);
    });
    localStorage.setItem("seimlai-depth-colors", JSON.stringify(colors));
    v.scene.requestRender();
  }, [ready, catalog, colors, stationColor, offset, surfaceEvents]);

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
      className={`seismic-map ${preview ? "map-preview" : ""} ${!preview && underground ? "has-underground-map" : ""}`}
      aria-label={preview ? "Geographic bounds preview" : "Live 3D seismic map"}
    >
      <div ref={host} className="cesium-host" />
      {!preview && underground && (
        <aside className="map-overlay underground-map" aria-label="Camera position and viewing direction on the surface">
          <div className="underground-map-title">
            <span>Camera · surface view</span>
            <div style={{ display: "flex", gap: 4 }}>
              <button type="button" aria-label="Zoom out orientation map" title="Zoom out" onClick={() => zoomMinimap(2)}>−</button>
              <button type="button" aria-label="Zoom in orientation map" title="Zoom in" onClick={() => zoomMinimap(0.5)}>+</button>
            </div>
          </div>
          <div className="underground-map-body">
            <div ref={minimapHost} className="cesium-host" />
            <div className="map-overlay" title="Camera pitch: 0° horizontal, −90° down, +90° up" style={{ position: "absolute", top: 6, left: 6, padding: "4px 6px", pointerEvents: "none", textAlign: "center" }}>
              <span ref={pitchLabel}>Pitch</span>
              <svg width="48" height="48" viewBox="0 0 48 48" aria-hidden="true" style={{ display: "block", margin: "0 auto" }}>
                <path d="M2 24H46" stroke="currentColor" strokeDasharray="3 3" opacity="0.5" />
                <g ref={pitchArrow} fill="none" stroke="var(--accent)" strokeWidth="2">
                  <path d="M24 24H44M39 20L44 24L39 28" />
                </g>
                <circle cx="24" cy="24" r="3" fill="var(--accent)" />
              </svg>
            </div>
            <div className="underground-camera" aria-hidden="true">
              <svg ref={cameraArrow} width="44" height="44" viewBox="0 0 44 44">
                <path d="M22 3L12 18H32Z" fill="#38bdf8" stroke="#102336" strokeWidth="2" />
              </svg>
              <span />
            </div>
          </div>
        </aside>
      )}
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
          <button onClick={fit} disabled={!ready || !validBounds} aria-label="Center on study area" title="Center on study area">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true" style={{ display: "block" }}>
              <circle cx="12" cy="12" r="7" />
              <circle cx="12" cy="12" r="2" />
              <path d="M12 2v3m0 14v3M2 12h3m14 0h3" />
            </svg>
          </button>
          {!preview && <button onClick={depthView} disabled={!ready || surfaceEvents || !catalog.events.length}>Depth view</button>}
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
          <style>{`
            .seismic-map .compass {
              top: 100px;
              left: 16px;
              right: auto;
            }
          `}</style>
          <aside className="map-overlay subsurface-controls">
            <span className="eyebrow">SUBSURFACE VIEW</span>
            <label className="inline-field">
              <input
                type="checkbox"
                checked={surfaceEvents}
                onChange={(e) => setSurfaceEvents(e.target.checked)}
              />{" "}
              Project events to surface (0 km)
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
                  disabled={surfaceEvents}
                  onChange={(e) => {
                    if (Number.isFinite(e.target.valueAsNumber))
                      setOffset(e.target.valueAsNumber);
                  }}
                />
              </label>
              <p>
                {surfaceEvents ? (
                  <>Events are projected to 0 km. Colors and details retain original catalog depths.</>
                ) : (
                  <>Display height = offset − depth × 1000. Zero assumes catalog
                    depth is measured from the ellipsoid. Adjust for the catalog
                    datum; no geoid correction is applied.</>
                )}
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
