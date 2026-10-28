"use client";

// Ensure CESIUM_BASE_URL is set before Cesium is imported
if (typeof window !== "undefined") {
  (window as any).CESIUM_BASE_URL = "/cesium/";
}

import React, { useState, useEffect, useRef, useMemo, useCallback, memo } from "react";
import { Viewer, ImageryLayer, useCesium } from "resium";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

import CesiumBasemapLayers from "./CesiumBasemapLayers";
import { useLayerStore } from "../../stores/layerStore";
import { useMapStore } from "../../stores/mapStore";
import { useUIStore } from "../../stores/uiStore";
import Logger from "../../utils/logger";
import { getApiBase } from "../../utils/apiBase";
import { GeoDataObject, LayerStyle } from "../../models/geodatamodel";
import { getBasemapKey } from "../../utils/basemaps";
import {
  basemapUsesGcj02,
  transformGeoJsonCoordinates,
  wgs84ToGcj02,
} from "../../utils/chinaCoords";
import {
  parseWMSUrl,
  parseWMTSUrl,
  parseWCSUrl,
  buildWMTSKvpTemplate,
  pickWebMercatorMatrixSet,
  isWebMercatorMatrixSet,
  geoJSONCache,
  fetchWithCorsProxy,
  getProxiedImageUrl,
  isExternalUrl,
  resolveLayerDataUrl,
} from "../../utils/geoMapHelpers";
import { GeoJSONNormalizer } from "../../utils/geojson-normalizer";

const DEFAULT_GEOMETRY_COLOR = "#2825eb";
const DEFAULT_POINT_FILL_COLOR = "#f92116";
const DEFAULT_POINT_RADIUS = 5;
const DEFAULT_POINT_FILL_OPACITY = 0.9;
const DEFAULT_POLYGON_FILL_OPACITY = 0.3;
const DEFAULT_POINT_OUTLINE_WIDTH = 2;
const SELECTED_ENTITY_COLOR = "#f97316";
const SELECTED_ENTITY_OUTLINE = "#111827";

type CesiumEntityStyleSnapshot = {
  point?: {
    color?: Cesium.Property;
    outlineColor?: Cesium.Property;
    outlineWidth?: Cesium.Property;
    pixelSize?: Cesium.Property;
  };
  polygon?: {
    material?: Cesium.MaterialProperty;
    outlineColor?: Cesium.Property;
    outlineWidth?: Cesium.Property;
  };
  polyline?: {
    material?: Cesium.MaterialProperty;
    width?: Cesium.Property;
  };
  billboard?: {
    color?: Cesium.Property;
    scale?: Cesium.Property;
  };
};

function cesiumColorFromCss(
  value: string | undefined,
  fallback: string,
  alpha?: number,
): Cesium.Color {
  const parsed = value ? Cesium.Color.fromCssColorString(value) : undefined;
  const fallbackColor = Cesium.Color.fromCssColorString(fallback) ?? Cesium.Color.WHITE;
  const color = parsed ?? fallbackColor;
  return alpha === undefined ? color : color.withAlpha(alpha);
}

function readEntityPropertyValue(
  entity: Cesium.Entity,
  field: string,
): string | number | boolean | undefined {
  const props = entity.properties;
  if (!props) return undefined;
  try {
    const prop = props[field];
    if (!prop) return undefined;
    const raw =
      typeof prop.getValue === "function"
        ? prop.getValue(Cesium.JulianDate.now())
        : prop;
    if (raw === undefined || raw === null) return undefined;
    return raw as string | number | boolean;
  } catch {
    return undefined;
  }
}

function resolveFeatureColor(
  entity: Cesium.Entity,
  layerStyle: LayerStyle | undefined,
  fallbackCss: string,
  alpha?: number,
): Cesium.Color {
  const conditions = layerStyle?.style_conditions;
  if (conditions && typeof conditions === "object") {
    for (const [field, config] of Object.entries(conditions)) {
      const colorMap =
        config && typeof config === "object"
          ? (config as { color_map?: Record<string, string> }).color_map
          : undefined;
      if (!colorMap) continue;
      const raw = readEntityPropertyValue(entity, field);
      if (raw === undefined) continue;
      const hex = colorMap[String(raw)];
      if (typeof hex === "string" && hex.trim()) {
        return cesiumColorFromCss(hex, fallbackCss, alpha);
      }
    }
  }
  return cesiumColorFromCss(layerStyle?.fill_color, fallbackCss, alpha);
}

function getPickedEntity(pickedObject: unknown): Cesium.Entity | undefined {
  if (!pickedObject || typeof pickedObject !== "object") return undefined;

  const picked = pickedObject as {
    id?: unknown;
    primitive?: { id?: unknown };
  };

  if (picked.id instanceof Cesium.Entity) {
    return picked.id;
  }

  if (picked.primitive?.id instanceof Cesium.Entity) {
    return picked.primitive.id;
  }

  return undefined;
}

// Legend component extracted and adapted
const Legend = memo(function Legend({
  wmsLayer,
  wmtsLayer,
  title,
  standalone = false,
}: {
  wmsLayer?: {
    baseUrl: string;
    layers: string;
    format: string;
    transparent: boolean;
  };
  wmtsLayer?: {
    wmtsLegendUrl: string;
    wmsLegendUrl: string;
    layerName: string;
    originalUrl: string;
  };
  title?: string;
  standalone?: boolean;
}) {
  const uniqueId = useMemo(() => {
    if (wmsLayer) {
      return `wms-${wmsLayer.baseUrl}-${wmsLayer.layers}`;
    } else if (wmtsLayer) {
      return `wmts-${wmtsLayer.originalUrl}`;
    }
    return "unknown";
  }, [wmsLayer?.baseUrl, wmsLayer?.layers, wmtsLayer?.originalUrl]);

  const [legendUrl, setLegendUrl] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [hasError, setHasError] = useState<boolean>(false);
  const [hasFallbackAttempted, setHasFallbackAttempted] = useState<boolean>(false);
  const [hasProxyAttempted, setHasProxyAttempted] = useState<boolean>(false);
  const [lastUniqueId, setLastUniqueId] = useState<string>("");
  const [isCollapsed, setIsCollapsed] = useState<boolean>(false);
  const [isImageMaximized, setIsImageMaximized] = useState<boolean>(false);
  const [originalLegendUrl, setOriginalLegendUrl] = useState<string>("");

  useEffect(() => {
    if (lastUniqueId !== uniqueId) {
      setIsLoading(true);
      setHasError(false);
      setHasFallbackAttempted(false);
      setHasProxyAttempted(false);
      setLastUniqueId(uniqueId);

      if (wmsLayer) {
        const wmsLegendUrl = `${wmsLayer.baseUrl}?service=WMS&request=GetLegendGraphic&layer=${wmsLayer.layers}&format=image/png`;
        setOriginalLegendUrl(wmsLegendUrl);
        setLegendUrl(wmsLegendUrl);
      } else if (wmtsLayer) {
        if (wmtsLayer.wmtsLegendUrl) {
          setOriginalLegendUrl(wmtsLayer.wmtsLegendUrl);
          setLegendUrl(wmtsLayer.wmtsLegendUrl);
        } else if (wmtsLayer.wmsLegendUrl) {
          setOriginalLegendUrl(wmtsLayer.wmsLegendUrl);
          setLegendUrl(wmtsLayer.wmsLegendUrl);
          setHasFallbackAttempted(true);
        } else {
          setHasError(true);
          setIsLoading(false);
        }
      } else {
        setHasError(true);
        setIsLoading(false);
      }
    }
  }, [uniqueId, wmsLayer, wmtsLayer, lastUniqueId]);

  if (!legendUrl || hasError) {
    return null;
  }

  const baseClasses = "bg-white p-2 rounded shadow text-black";
  const positionClasses = standalone ? "absolute bottom-2 right-2 z-[9999]" : "";
  const sizeClasses = "w-[15vw] min-w-[200px]";

  return (
    <div className={`${baseClasses} ${positionClasses} ${sizeClasses}`.trim()}>
      <div className="flex items-center justify-between mb-2 text-black">
        {title && (
          <h4
            className={`font-bold text-sm flex-1 mr-2 ${isCollapsed ? "truncate" : "break-words"
              }`}
          >
            {title}
          </h4>
        )}
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="flex-shrink-0 w-6 h-6 flex items-center justify-center rounded hover:bg-gray-100 transition-colors pointer-events-auto"
          title={isCollapsed ? "展开图例" : "折叠图例"}
          aria-label={isCollapsed ? "展开图例" : "折叠图例"}
        >
          <svg
            className={`w-4 h-4 transition-transform ${isCollapsed ? "rotate-0" : "rotate-180"}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {!isCollapsed && (
        <>
          {isLoading && (
            <div className="flex items-center justify-center h-16 text-xs text-gray-500">
              正在加载图例...
            </div>
          )}
          <div className="relative group cursor-pointer pointer-events-auto">
            <img
              src={legendUrl}
              alt="图层图例"
              className={`w-full object-contain transition-all duration-300 ease-in-out ${isImageMaximized ? "max-h-none" : "max-h-50"
                }`}
              style={{ display: isLoading ? "none" : "block" }}
              onClick={() => setIsImageMaximized(!isImageMaximized)}
              title={isImageMaximized ? "点击缩小" : "点击放大"}
              onLoad={() => {
                setIsLoading(false);
                Logger.log("Legend loaded successfully:", legendUrl);
              }}
              onError={(e) => {
                Logger.warn("Legend image failed to load:", legendUrl);
                if (
                  wmtsLayer &&
                  legendUrl === wmtsLayer.wmtsLegendUrl &&
                  wmtsLayer.wmsLegendUrl &&
                  !hasFallbackAttempted
                ) {
                  Logger.log("Trying WMS fallback for WMTS legend");
                  setHasFallbackAttempted(true);
                  setOriginalLegendUrl(wmtsLayer.wmsLegendUrl);
                  setLegendUrl(wmtsLayer.wmsLegendUrl);
                  setIsLoading(true);
                } else if (!hasProxyAttempted && originalLegendUrl && isExternalUrl(originalLegendUrl)) {
                  Logger.log("Trying image proxy for legend:", originalLegendUrl);
                  setHasProxyAttempted(true);
                  setLegendUrl(getProxiedImageUrl(originalLegendUrl));
                  setIsLoading(true);
                } else {
                  Logger.log("Legend loading failed permanently");
                  setHasError(true);
                  setIsLoading(false);
                }
              }}
            />
          </div>
        </>
      )}
    </div>
  );
});

// GeoJson Layer Fetcher and Component Wrapper
const CesiumGeoJSONLayer = memo(function CesiumGeoJSONLayer({
  url,
  layerStyle,
  layerId,
  zoomOnLoad,
  displayOnGcj02Basemap,
}: {
  url: string;
  layerStyle?: LayerStyle;
  layerId: string | number;
  zoomOnLoad: boolean;
  /** Amap tiles are GCJ-02; stored layers are WGS84 — shift for display only. */
  displayOnGcj02Basemap: boolean;
}) {
  const { viewer, scene, dataSourceCollection } = useCesium();
  const [data, setData] = useState<any>(null);
  const dataSourceRef = useRef<Cesium.GeoJsonDataSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    const resolvedUrl = resolveLayerDataUrl(url);
    if (!resolvedUrl) {
      Logger.error("GeoJSON layer missing data_link", { layerId, url });
      return;
    }

    const cachedData = geoJSONCache.get(resolvedUrl);
    if (cachedData) {
      setData(cachedData);
      return;
    }

    let requestUrl = resolvedUrl;
    try {
      const testU = new URL(resolvedUrl, typeof window !== "undefined" ? window.location.origin : undefined);
      if (
        (/wfs/i.test(testU.search) ||
          testU.searchParams.get("service")?.toUpperCase() === "WFS") &&
        !testU.searchParams.get("srsName")
      ) {
        testU.searchParams.set("srsName", "EPSG:4326");
        requestUrl = testU.toString();
      }
    } catch (e) { /* relative /api/stream URLs are fine as-is */ }

    fetchWithCorsProxy(requestUrl, {
      headers: { Accept: "application/json, application/geo+json, */*;q=0.1" },
    })
      .then((res) => {
        if (!res.ok && requestUrl !== resolvedUrl) {
          return fetchWithCorsProxy(resolvedUrl, {
            headers: { Accept: "application/json, application/geo+json, */*;q=0.1" },
          });
        }
        return res;
      })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status} for ${resolvedUrl}`);
        }
        return res.text();
      })
      .then((text) => {
        try {
          const json = JSON.parse(text);
          const normalized = GeoJSONNormalizer.normalize(json) || json;
          geoJSONCache.set(resolvedUrl, normalized);
          if (!cancelled) setData(normalized);
        } catch (e) {
          Logger.error("Failed to parse JSON for GeoJSON layer", e, { url: resolvedUrl });
        }
      })
      .catch((err) => Logger.error("Failed to load GeoJSON", err, { url: resolvedUrl }));
    return () => { cancelled = true; };
  }, [url, layerId]);

  const strokeColor = useMemo(
    () =>
      cesiumColorFromCss(
        layerStyle?.stroke_color,
        DEFAULT_GEOMETRY_COLOR,
        layerStyle?.stroke_opacity ?? 1.0,
      ),
    [layerStyle?.stroke_color, layerStyle?.stroke_opacity],
  );

  const polygonFillColor = useMemo(
    () =>
      cesiumColorFromCss(
        layerStyle?.fill_color,
        DEFAULT_GEOMETRY_COLOR,
        layerStyle?.fill_opacity ?? DEFAULT_POLYGON_FILL_OPACITY,
      ),
    [layerStyle?.fill_color, layerStyle?.fill_opacity],
  );

  const pointFillColor = useMemo(
    () =>
      cesiumColorFromCss(
        layerStyle?.fill_color,
        DEFAULT_POINT_FILL_COLOR,
        layerStyle?.fill_opacity ?? DEFAULT_POINT_FILL_OPACITY,
      ),
    [layerStyle?.fill_color, layerStyle?.fill_opacity],
  );

  const pointOutlineColor = useMemo(() => layerStyle?.stroke_color
    ? strokeColor
    : Cesium.Color.WHITE.withAlpha(0.95), [layerStyle?.stroke_color, strokeColor]);

  // Apply styling reactively across all entities (supports style_conditions color_map)
  const applyStyles = useCallback((ds: Cesium.GeoJsonDataSource) => {
    if (!ds || !ds.entities) return;
    const entities = ds.entities.values;
    const hasConditions =
      !!layerStyle?.style_conditions &&
      Object.keys(layerStyle.style_conditions).length > 0;
    const polygonAlpha = layerStyle?.fill_opacity ?? DEFAULT_POLYGON_FILL_OPACITY;
    const pointAlpha = layerStyle?.fill_opacity ?? DEFAULT_POINT_FILL_OPACITY;

    for (let i = 0; i < entities.length; i++) {
      const entity = entities[i];
      const featurePolygonFill = hasConditions
        ? resolveFeatureColor(
            entity,
            layerStyle,
            layerStyle?.fill_color || DEFAULT_GEOMETRY_COLOR,
            polygonAlpha,
          )
        : polygonFillColor;
      const featurePointFill = hasConditions
        ? resolveFeatureColor(
            entity,
            layerStyle,
            layerStyle?.fill_color || DEFAULT_POINT_FILL_COLOR,
            pointAlpha,
          )
        : pointFillColor;

      if (entity.polygon) {
        entity.polygon.material = new Cesium.ColorMaterialProperty(featurePolygonFill);
        entity.polygon.outlineColor = new Cesium.ConstantProperty(strokeColor);
        entity.polygon.outlineWidth = new Cesium.ConstantProperty(layerStyle?.stroke_weight ?? 2);
      }
      if (entity.polyline) {
        // Prefer categorical color for lines when style_conditions is set.
        const lineColor = hasConditions
          ? resolveFeatureColor(
              entity,
              layerStyle,
              layerStyle?.stroke_color || DEFAULT_GEOMETRY_COLOR,
              layerStyle?.stroke_opacity ?? 1.0,
            )
          : strokeColor;
        entity.polyline.material = new Cesium.ColorMaterialProperty(lineColor);
        entity.polyline.width = new Cesium.ConstantProperty(layerStyle?.stroke_weight ?? 2);
      }
      // For point features
      if (entity.position && !entity.polygon && !entity.polyline) {
        // Remove the default pin, rather than hiding it. Ground-clamped points
        // also use a billboard internally; a hidden BillboardGraphics causes
        // BillboardVisualizer to clear the point's shared primitive each frame.
        if (entity.billboard) {
          entity.billboard = undefined;
        }
        // Initialize point graphic if not present
        if (!entity.point) {
          entity.point = new Cesium.PointGraphics();
        }
        entity.point.show = new Cesium.ConstantProperty(true);
        entity.point.color = new Cesium.ConstantProperty(featurePointFill);
        entity.point.outlineColor = new Cesium.ConstantProperty(pointOutlineColor);
        entity.point.outlineWidth = new Cesium.ConstantProperty(layerStyle?.stroke_weight ?? DEFAULT_POINT_OUTLINE_WIDTH);
        entity.point.pixelSize = new Cesium.ConstantProperty((layerStyle?.radius ?? DEFAULT_POINT_RADIUS) * 2);
        entity.point.heightReference = new Cesium.ConstantProperty(Cesium.HeightReference.CLAMP_TO_GROUND);
        entity.point.disableDepthTestDistance = new Cesium.ConstantProperty(Number.POSITIVE_INFINITY);
      }
    }
  }, [pointFillColor, pointOutlineColor, polygonFillColor, strokeColor, layerStyle]);

  const applyStylesRef = useRef(applyStyles);
  useEffect(() => {
    applyStylesRef.current = applyStyles;
    if (dataSourceRef.current) {
      applyStyles(dataSourceRef.current);
      scene?.requestRender();
    }
  }, [applyStyles, scene]);

  useEffect(() => {
    if (!data || !dataSourceCollection || !scene || !viewer) return;
    let cancelled = false;
    const source = new Cesium.GeoJsonDataSource(String(layerId));
    // Layers are stored as WGS84 (Amap POIs are converted on ingest). Tianditu /
    // OSM match WGS84; Amap basemap tiles are GCJ-02, so shift for display only.
    const displayData = displayOnGcj02Basemap
      ? transformGeoJsonCoordinates(data, wgs84ToGcj02)
      : data;

    // Finish parsing and apply the latest style before Cesium creates primitives.
    // Timed style retries can run before asynchronous loading has completed.
    void source.load(displayData, { clampToGround: true }).then(async () => {
      if (cancelled || viewer.isDestroyed()) return;
      applyStylesRef.current(source);
      dataSourceRef.current = source;
      await dataSourceCollection.add(source);
      if (cancelled || viewer.isDestroyed()) {
        if (!dataSourceCollection.isDestroyed()) dataSourceCollection.remove(source, true);
        return;
      }
      scene.requestRender();
      // Direct PostGIS layers have no bounding_box; fit the loaded geometry.
      if (zoomOnLoad && source.entities.values.length > 0) {
        flyToDataSource(viewer, source);
      }
    }).catch((err) => {
      if (!cancelled) Logger.error("Failed to initialize GeoJSON layer", err);
    });

    return () => {
      cancelled = true;
      if (dataSourceRef.current === source) dataSourceRef.current = null;
      if (!dataSourceCollection.isDestroyed()) dataSourceCollection.remove(source, true);
    };
  }, [data, dataSourceCollection, displayOnGcj02Basemap, layerId, scene, viewer, zoomOnLoad]);

  return null;
});

/** Minimum camera pull-back for point clusters (metres). 500m fills the screen. */
const MIN_POINT_VIEW_RADIUS_M = 3000;
/** Minimum lon/lat span when flying to a tiny bbox (~3–4 km). */
const MIN_POINT_VIEW_SPAN_DEG = 0.03;

function expandTinyBounds(
  bounds: [number, number, number, number],
): [number, number, number, number] {
  let [west, south, east, north] = bounds;
  const width = Math.max(0, east - west);
  const height = Math.max(0, north - south);
  if (width < MIN_POINT_VIEW_SPAN_DEG) {
    const pad = (MIN_POINT_VIEW_SPAN_DEG - width) / 2;
    west -= pad;
    east += pad;
  }
  if (height < MIN_POINT_VIEW_SPAN_DEG) {
    const pad = (MIN_POINT_VIEW_SPAN_DEG - height) / 2;
    south -= pad;
    north += pad;
  }
  return [west, south, east, north];
}

function flyToDataSource(viewer: Cesium.Viewer, source: Cesium.DataSource) {
  const entities = source.entities.values;
  if (entities.length > 0 && entities.every((entity) => entity.point && entity.position)) {
    const positions = entities
      .map((entity) => entity.position?.getValue(viewer.clock.currentTime))
      .filter((position): position is Cesium.Cartesian3 => position !== undefined);
    if (positions.length > 0) {
      const sphere = Cesium.BoundingSphere.fromPoints(positions);
      // A single/coincident point has no spatial extent. Pull back far enough
      // that a city-block context remains visible, not just the point glyph.
      sphere.radius = Math.max(sphere.radius, MIN_POINT_VIEW_RADIUS_M);
      viewer.camera.flyToBoundingSphere(sphere, {
        duration: 1.5,
        offset: new Cesium.HeadingPitchRange(
          0,
          -Cesium.Math.PI_OVER_TWO,
          sphere.radius * 2.5,
        ),
      });
      return;
    }
  }
  void viewer.flyTo(source, { duration: 1.5 });
}

const VECTOR_GEOJSON_LAYER_TYPES = new Set([
  "WFS",
  "VECTOR",
  "UPLOADED",
  "GEOJSON",
  "GEOJSON POINTS",
  "GEOJSON POLYGONS",
  "GEOJSON LINES",
  "POINT",
  "POLYGON",
  "LINE",
  "LINESTRING",
  "MULTIPOINT",
  "MULTIPOLYGON",
  "MULTILINESTRING",
]);

function isVectorGeoJsonLayer(layer: GeoDataObject): boolean {
  const type = layer.layer_type?.toUpperCase().trim() || "";
  if (VECTOR_GEOJSON_LAYER_TYPES.has(type)) return true;
  const link = (layer.data_link || "").toLowerCase();
  return (
    link.includes("json") ||
    link.includes("/api/stream/") ||
    link.endsWith(".geojson")
  );
}

function getLayerBounds(layer: GeoDataObject): [number, number, number, number] | null {
  const bbox = layer.bounding_box;
  let bounds: [number, number, number, number] | null = null;

  if (typeof bbox === "string" && bbox.toUpperCase().includes("POLYGON")) {
    const match = bbox.match(/POLYGON\s*\(\((.+?)\)\)/i);
    if (match) {
      const coords = match[1]
        .split(",")
        .map((pair) => pair.trim().split(/\s+/).map(Number))
        .filter(([lng, lat]) => Number.isFinite(lng) && Number.isFinite(lat));

      if (coords.length > 0) {
        const lats = coords.map(([, lat]) => lat);
        const lngs = coords.map(([lng]) => lng);
        bounds = [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)];
      }
    }
  } else if (Array.isArray(bbox) && bbox.length >= 4) {
    const [minX, minY, maxX, maxY] = bbox.map(Number);
    bounds = [minX, minY, maxX, maxY];
  }

  if (!bounds || bounds.some((value) => !Number.isFinite(value))) return null;

  return bounds;
}

function flyToBounds(
  viewer: Cesium.Viewer,
  bounds: [number, number, number, number],
  toGcj02 = false,
) {
  let [west, south, east, north] = expandTinyBounds(bounds);
  if (toGcj02) {
    const [wLon, sLat] = wgs84ToGcj02(west, south);
    const [eLon, nLat] = wgs84ToGcj02(east, north);
    west = wLon;
    south = sLat;
    east = eLon;
    north = nLat;
  }
  viewer.camera.flyTo({
    destination: Cesium.Rectangle.fromDegrees(west, south, east, north),
    duration: 1.5,
  });
}

export default function CesiumMapClient() {
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const [viewer, setViewer] = useState<Cesium.Viewer | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<Cesium.Entity | null>(null);
  const selectedStyleRef = useRef<{
    entity: Cesium.Entity;
    snapshot: CesiumEntityStyleSnapshot;
  } | null>(null);
  const [propertySearch, setPropertySearch] = useState("");
  const layers = useLayerStore((state) => state.layers);
  const zoomTo = useLayerStore((state) => state.zoomTo);
  const setZoomTo = useLayerStore((state) => state.setZoomTo);
  const basemap = useMapStore((state) => state.basemap);
  const displayOnGcj02Basemap = basemapUsesGcj02(getBasemapKey(basemap));

  const visibleLayers = useMemo(() => layers.filter((l) => l.visible), [layers]);

  const restoreSelectedEntityHighlight = useCallback(() => {
    const selectedStyle = selectedStyleRef.current;
    if (!selectedStyle) return;

    const { entity, snapshot } = selectedStyle;
    if (entity.point && snapshot.point) {
      entity.point.color = snapshot.point.color;
      entity.point.outlineColor = snapshot.point.outlineColor;
      entity.point.outlineWidth = snapshot.point.outlineWidth;
      entity.point.pixelSize = snapshot.point.pixelSize;
    }
    if (entity.polygon && snapshot.polygon) {
      if (snapshot.polygon.material) {
        entity.polygon.material = snapshot.polygon.material;
      }
      entity.polygon.outlineColor = snapshot.polygon.outlineColor;
      entity.polygon.outlineWidth = snapshot.polygon.outlineWidth;
    }
    if (entity.polyline && snapshot.polyline) {
      if (snapshot.polyline.material) {
        entity.polyline.material = snapshot.polyline.material;
      }
      entity.polyline.width = snapshot.polyline.width;
    }
    if (entity.billboard && snapshot.billboard) {
      entity.billboard.color = snapshot.billboard.color;
      entity.billboard.scale = snapshot.billboard.scale;
    }

    selectedStyleRef.current = null;
  }, []);

  const applySelectedEntityHighlight = useCallback((entity: Cesium.Entity) => {
    if (selectedStyleRef.current?.entity === entity) return;

    restoreSelectedEntityHighlight();

    const snapshot: CesiumEntityStyleSnapshot = {};
    const fillColor = cesiumColorFromCss(SELECTED_ENTITY_COLOR, "#f97316", 0.9);
    const outlineColor = cesiumColorFromCss(SELECTED_ENTITY_OUTLINE, "#111827", 1);
    const material = new Cesium.ColorMaterialProperty(fillColor);

    if (entity.point) {
      const currentPixelSize = Number(
        entity.point.pixelSize?.getValue(Cesium.JulianDate.now()) ?? DEFAULT_POINT_RADIUS * 2,
      );
      snapshot.point = {
        color: entity.point.color,
        outlineColor: entity.point.outlineColor,
        outlineWidth: entity.point.outlineWidth,
        pixelSize: entity.point.pixelSize,
      };
      entity.point.color = new Cesium.ConstantProperty(fillColor);
      entity.point.outlineColor = new Cesium.ConstantProperty(outlineColor);
      entity.point.outlineWidth = new Cesium.ConstantProperty(4);
      entity.point.pixelSize = new Cesium.ConstantProperty(Math.max(currentPixelSize + 8, 18));
    }

    if (entity.polygon) {
      snapshot.polygon = {
        material: entity.polygon.material,
        outlineColor: entity.polygon.outlineColor,
        outlineWidth: entity.polygon.outlineWidth,
      };
      entity.polygon.material = material;
      entity.polygon.outlineColor = new Cesium.ConstantProperty(outlineColor);
      entity.polygon.outlineWidth = new Cesium.ConstantProperty(4);
    }

    if (entity.polyline) {
      const currentWidth = Number(
        entity.polyline.width?.getValue(Cesium.JulianDate.now()) ?? 2,
      );
      snapshot.polyline = {
        material: entity.polyline.material,
        width: entity.polyline.width,
      };
      entity.polyline.material = material;
      entity.polyline.width = new Cesium.ConstantProperty(Math.max(currentWidth + 3, 5));
    }

    if (entity.billboard) {
      const currentScale = Number(entity.billboard.scale?.getValue(Cesium.JulianDate.now()) ?? 1);
      snapshot.billboard = {
        color: entity.billboard.color,
        scale: entity.billboard.scale,
      };
      entity.billboard.color = new Cesium.ConstantProperty(fillColor);
      entity.billboard.scale = new Cesium.ConstantProperty(Math.max(currentScale * 1.25, 1.25));
    }

    selectedStyleRef.current = { entity, snapshot };
  }, [restoreSelectedEntityHighlight]);

  // Sync selection state from Cesium viewer and customize selection indicator style
  useEffect(() => {
    if (!viewer) return;

    const applySelectionIndicatorStyle = () => {
      try {
        const container = viewer.container;
        const pathElement = container.querySelector(".cesium-selection-wrapper path");
        if (pathElement) {
          // Change default selection box corners SVG path to a teardrop map pin pointing to (0,0)
          pathElement.setAttribute(
            "d",
            "M 0 0 C -12 -12 -18 -24 -18 -36 A 18 18 0 1 1 18 -36 C 18 -24 12 -12 0 0 Z M 0 -43 A 7 7 0 1 0 0 -29 A 7 7 0 1 0 0 -43 Z"
          );
          // Apply custom inline styles to override default widgets.css green/black styling
          const htmlElement = pathElement as SVGElement;
          htmlElement.style.fill = "#FF6B35"; // Theme primary orange
          htmlElement.style.stroke = "#FFFFFF"; // Clean white border
          htmlElement.style.strokeWidth = "2px";
        }
      } catch (e) {
        Logger.warn("Failed to customize selection indicator path:", e);
      }
    };

    const handleSelectionChange = (entity: Cesium.Entity | undefined) => {
      if (entity) {
        applySelectedEntityHighlight(entity);
      } else {
        restoreSelectedEntityHighlight();
      }
      setSelectedEntity(entity || null);
      setPropertySearch(""); // Reset search on entity change

      if (entity) {
        // Delay slightly to ensure Cesium has mounted and updated the selection wrapper DOM
        setTimeout(applySelectionIndicatorStyle, 50);
      }
    };

    viewer.selectedEntityChanged.addEventListener(handleSelectionChange);

    // Initial sync
    if (viewer.selectedEntity) {
      setSelectedEntity(viewer.selectedEntity);
      setTimeout(applySelectionIndicatorStyle, 50);
    }

    return () => {
      viewer.selectedEntityChanged.removeEventListener(handleSelectionChange);
      restoreSelectedEntityHighlight();
    };
  }, [applySelectedEntityHighlight, restoreSelectedEntityHighlight, viewer]);

  // Change mouse cursor to pointer and explicitly select clicked entities.
  useEffect(() => {
    if (!viewer) return;
    const scene = viewer.scene;
    const canvas = scene.canvas;

    const handler = new Cesium.ScreenSpaceEventHandler(canvas);

    const findNearestPointEntity = (position: Cesium.Cartesian2) => {
      const time = viewer.clock.currentTime;
      let nearestEntity: Cesium.Entity | undefined;
      let nearestDistance = Number.POSITIVE_INFINITY;

      for (let i = 0; i < viewer.dataSources.length; i++) {
        const dataSource = viewer.dataSources.get(i);
        const entities = dataSource.entities?.values || [];

        for (const entity of entities) {
          if (!entity.position || !entity.point) continue;

          const worldPosition = entity.position.getValue(time);
          if (!worldPosition) continue;

          const canvasPosition = scene.cartesianToCanvasCoordinates(worldPosition);
          if (!canvasPosition) continue;

          const dx = canvasPosition.x - position.x;
          const dy = canvasPosition.y - position.y;
          const distance = Math.sqrt(dx * dx + dy * dy);
          const pixelSize = Number(entity.point.pixelSize?.getValue(time) ?? 0);
          const pickRadius = Math.max(18, pixelSize / 2 + 6);

          if (distance <= pickRadius && distance < nearestDistance) {
            nearestDistance = distance;
            nearestEntity = entity;
          }
        }
      }

      return nearestEntity;
    };

    const findEntityAtPosition = (position: Cesium.Cartesian2) => {
      const pickedEntity = getPickedEntity(scene.pick(position));
      if (pickedEntity) return pickedEntity;

      const pickedObjects = scene.drillPick(position, 8);
      for (const pickedObject of pickedObjects) {
        const drilledEntity = getPickedEntity(pickedObject);
        if (drilledEntity) return drilledEntity;
      }

      return findNearestPointEntity(position);
    };

    handler.setInputAction((movement: { endPosition: Cesium.Cartesian2 }) => {
      if (findEntityAtPosition(movement.endPosition)) {
        canvas.style.cursor = "pointer";
      } else {
        canvas.style.cursor = "default";
      }
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    handler.setInputAction((click: { position: Cesium.Cartesian2 }) => {
      const entity = findEntityAtPosition(click.position);
      if (entity) {
        viewer.selectedEntity = entity;
        return;
      }

      viewer.selectedEntity = undefined;
      setSelectedEntity(null);
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    const handleCanvasClick = (event: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const position = new Cesium.Cartesian2(
        event.clientX - rect.left,
        event.clientY - rect.top,
      );
      const entity = findEntityAtPosition(position);
      if (entity) {
        viewer.selectedEntity = entity;
        return;
      }

      viewer.selectedEntity = undefined;
      setSelectedEntity(null);
    };

    canvas.addEventListener("click", handleCanvasClick);

    return () => {
      canvas.removeEventListener("click", handleCanvasClick);
      handler.destroy();
      canvas.style.cursor = "default";
    };
  }, [viewer]);

  const descriptionHtml = useMemo(() => {
    if (!selectedEntity || !selectedEntity.description) return null;
    try {
      const val = selectedEntity.description.getValue(Cesium.JulianDate.now());
      return val ? String(val) : null;
    } catch (e) {
      Logger.error("Failed to get selected entity description:", e);
      return null;
    }
  }, [selectedEntity]);

  const propertiesList = useMemo(() => {
    if (!selectedEntity || !selectedEntity.properties) return [];
    try {
      const names = selectedEntity.properties.propertyNames;
      const list: { key: string; value: unknown }[] = [];
      for (const name of names) {
        const prop = selectedEntity.properties[name];
        if (prop) {
          const val = prop.getValue(Cesium.JulianDate.now());
          if (val !== undefined && val !== null) {
            list.push({ key: name, value: val });
          }
        }
      }
      return list;
    } catch (e) {
      Logger.error("Failed to get selected entity properties:", e);
      return [];
    }
  }, [selectedEntity]);

  const filteredProperties = useMemo(() => {
    if (!propertySearch.trim()) return propertiesList;
    const searchLower = propertySearch.toLowerCase();
    return propertiesList.filter(
      ({ key, value }) =>
        key.toLowerCase().includes(searchLower) ||
        String(value).toLowerCase().includes(searchLower)
    );
  }, [propertiesList, propertySearch]);

  const terrainProvider = useMemo(() => new Cesium.EllipsoidTerrainProvider(), []);

  // Handle bounding box zoom for non-tiled or new layers
  const zoomedLayers = useRef<Set<string | number>>(new Set());
  useEffect(() => {
    if (!viewerRef.current) return;
    const viewer = viewerRef.current;

    visibleLayers.forEach((layer) => {
      if (zoomedLayers.current.has(layer.id)) return;

      const bounds = getLayerBounds(layer);
      if (bounds) {
        flyToBounds(viewer, bounds, displayOnGcj02Basemap);
        zoomedLayers.current.add(layer.id);
      }
    });
  }, [visibleLayers, displayOnGcj02Basemap]);

  useEffect(() => {
    if (zoomTo == null || !viewer) return;

    const layer = layers.find((item) => item.id === zoomTo);
    if (!layer) {
      Logger.warn("Layer not found with ID:", zoomTo);
      setZoomTo(null);
      return;
    }

    const bounds = getLayerBounds(layer);
    if (bounds) {
      flyToBounds(viewer, bounds, displayOnGcj02Basemap);
      setZoomTo(null);
      return;
    }

    const dataSource = viewer.dataSources.getByName(String(layer.id))[0];
    if (dataSource) {
      flyToDataSource(viewer, dataSource);
    } else {
      Logger.warn("No bounding box or loaded data source available for layer:", layer.name);
    }

    setZoomTo(null);
  }, [zoomTo, layers, viewer, setZoomTo, displayOnGcj02Basemap]);

  // Gather legends
  const legendComponents = useMemo(() => {
    return visibleLayers
      .map((layer) => {
        if (layer.layer_type?.toUpperCase() === "WMS") {
          const wmsLayerParsed = parseWMSUrl(layer.data_link);
          return <Legend key={`wms-${layer.id}`} wmsLayer={wmsLayerParsed} title={layer.title || layer.name} />;
        } else if (layer.layer_type?.toUpperCase() === "WCS") {
          const wcsParsed = parseWCSUrl(layer.data_link);
          return (
            <Legend
              key={`wcs-${layer.id}`}
              wmsLayer={{
                baseUrl: wcsParsed.baseUrl,
                layers: wcsParsed.layers,
                format: wcsParsed.format,
                transparent: wcsParsed.transparent,
              }}
              title={layer.title || layer.name}
            />
          );
        } else if (layer.layer_type?.toUpperCase() === "WMTS") {
          const wmtsLayerParsed = parseWMTSUrl(layer.data_link);
          const propMatrixSets = (layer as any).properties?.tile_matrix_sets as string[] | undefined;
          const candidateSetsRaw = propMatrixSets && propMatrixSets.length ? propMatrixSets : ["EPSG:3857", "GoogleMapsCompatible", "WebMercatorQuad"];
          const candidateSets = candidateSetsRaw.filter((s) => isWebMercatorMatrixSet(s));
          const chosen = pickWebMercatorMatrixSet(candidateSets) || pickWebMercatorMatrixSet(candidateSetsRaw) || candidateSetsRaw[0];
          if (!chosen || !isWebMercatorMatrixSet(chosen)) {
            return null;
          }
          return <Legend key={`wmts-${layer.id}`} wmtsLayer={wmtsLayerParsed} title={layer.title || layer.name} />;
        }
        return null;
      })
      .filter(Boolean);
  }, [visibleLayers]);

  return (
    <div className="relative w-full h-full">
      <Viewer
        full
        ref={(e) => {
          if (e && e.cesiumElement) {
            viewerRef.current = e.cesiumElement;
            setViewer(e.cesiumElement);
            if (process.env.NODE_ENV !== "production") {
              (window as any).__nalamapCesiumViewer = e.cesiumElement;
            }
          }
        }}
        terrainProvider={terrainProvider}
        baseLayerPicker={false}
        baseLayer={false}
        geocoder={false}
        homeButton={true}
        infoBox={false}
        sceneModePicker={true}
        navigationHelpButton={false}
        animation={false}
        timeline={false}
      >
        <CesiumBasemapLayers />

        {/* User Layers */}
        {visibleLayers.map((layer) => {
          if (layer.layer_type?.toUpperCase() === "WMS") {
            const parsed = parseWMSUrl(layer.data_link);
            const wmsProvider = new Cesium.WebMapServiceImageryProvider({
              url: parsed.baseUrl,
              layers: parsed.layers,
              parameters: {
                format: parsed.format,
                transparent: parsed.transparent,
              },
            });
            return <ImageryLayer key={layer.id} imageryProvider={wmsProvider} alpha={layer.style?.fill_opacity ?? 1.0} />;
          } else if (layer.layer_type?.toUpperCase() === "WCS") {
            const parsed = parseWCSUrl(layer.data_link);
            const wcsProvider = new Cesium.WebMapServiceImageryProvider({
              url: parsed.baseUrl,
              layers: parsed.layers,
              parameters: {
                format: parsed.format,
                transparent: parsed.transparent,
              },
            });
            return <ImageryLayer key={layer.id} imageryProvider={wcsProvider} alpha={layer.style?.fill_opacity ?? 1.0} />;
          } else if (layer.layer_type?.toUpperCase() === "WMTS") {
            const parsed = parseWMTSUrl(layer.data_link);
            const propMatrixSets = (layer as any).properties?.tile_matrix_sets as string[] | undefined;
            const candidateSetsRaw = propMatrixSets && propMatrixSets.length ? propMatrixSets : ["EPSG:3857", "GoogleMapsCompatible", "WebMercatorQuad"];
            const candidateSets = candidateSetsRaw.filter((s) => isWebMercatorMatrixSet(s));
            const chosenSet = pickWebMercatorMatrixSet(candidateSets) || pickWebMercatorMatrixSet(candidateSetsRaw) || candidateSetsRaw[0];

            if (!chosenSet || !isWebMercatorMatrixSet(chosenSet)) {
              return null;
            }

            const anyParsed: any = parsed as any;
            const desiredBase = anyParsed.wmtsKvpBase || "";
            const initialVersion = anyParsed.version || "1.0.0";

            const tileUrlTemplate = buildWMTSKvpTemplate(
              desiredBase,
              anyParsed.fullLayerName || anyParsed.layerName,
              chosenSet,
              "image/png",
              initialVersion,
            );

            const provider = new Cesium.UrlTemplateImageryProvider({
              url: tileUrlTemplate,
            });

            return <ImageryLayer key={layer.id} imageryProvider={provider} alpha={layer.style?.fill_opacity ?? 1.0} />;
          } else if (isVectorGeoJsonLayer(layer)) {
            return (
              <CesiumGeoJSONLayer
                key={`${layer.id}:${displayOnGcj02Basemap ? "gcj02" : "wgs84"}`}
                url={layer.data_link}
                layerId={layer.id}
                layerStyle={layer.style}
                zoomOnLoad={!getLayerBounds(layer)}
                displayOnGcj02Basemap={displayOnGcj02Basemap}
              />
            );
          }
          return null;
        })}

        {/* Render legends inside a floating div */}
        {legendComponents.length > 0 && (
          <div className="absolute bottom-2 right-2 z-[9999] space-y-2 pointer-events-none">
            {legendComponents}
          </div>
        )}
      </Viewer>

      {/* Floating details panel */}
      {selectedEntity && (
        <div
          className="absolute top-4 left-4 z-[9999] w-80 max-h-[80vh] bg-white dark:bg-slate-900 rounded-lg shadow-2xl border border-gray-200 dark:border-gray-800 overflow-hidden flex flex-col pointer-events-auto"
          style={{ fontFamily: 'system-ui, sans-serif' }}
        >
          {/* Header */}
          <div className="bg-primary-800 text-white px-4 py-3 flex items-center justify-between">
            <h3 className="font-bold text-sm truncate max-w-[80%]" title={selectedEntity.name || "要素详细信息"}>
              {selectedEntity.name || "要素详细信息"}
            </h3>
            <button
              onClick={() => {
                if (viewerRef.current) {
                  viewerRef.current.selectedEntity = undefined as any;
                }
                setSelectedEntity(null);
              }}
              className="text-white hover:text-gray-200 transition-colors focus:outline-none"
              aria-label="关闭详情"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Search bar (only show if we have properties list and no custom HTML description) */}
          {!descriptionHtml && propertiesList.length > 5 && (
            <div className="p-2 border-b border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-slate-950">
              <input
                type="text"
                placeholder="搜索属性..."
                value={propertySearch}
                onChange={(e) => setPropertySearch(e.target.value)}
                className="w-full text-xs px-2.5 py-1.5 border border-gray-200 dark:border-gray-700 rounded bg-white dark:bg-slate-900 text-gray-850 dark:text-gray-200 focus:outline-none focus:border-primary-500"
              />
            </div>
          )}

          {/* Content */}
          <div className="p-4 overflow-y-auto flex-1 text-gray-800 dark:text-gray-200">
            {descriptionHtml ? (
              <div
                className="cesium-info-html prose prose-sm max-w-none text-sm break-words dark:prose-invert"
                dangerouslySetInnerHTML={{ __html: descriptionHtml }}
              />
            ) : (
              <div>
                {propertiesList.length > 0 ? (
                  <table className="w-full text-xs border-collapse">
                    <tbody>
                      {filteredProperties.map(({ key, value }) => {
                        const valStr = typeof value === 'object' ? JSON.stringify(value) : String(value);
                        return (
                          <tr key={key} className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-slate-800/50">
                            <th className="text-left font-semibold text-gray-500 dark:text-gray-400 p-2 w-1/3 align-top break-all select-all">{key}</th>
                            <td className="text-left text-gray-800 dark:text-gray-200 p-2 break-all select-all">{valStr}</td>
                          </tr>
                        );
                      })}
                      {filteredProperties.length === 0 && (
                        <tr>
                          <td className="text-gray-550 text-center py-4">未找到匹配的属性</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                ) : (
                  <p className="text-gray-500 text-center py-4">无属性信息</p>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
