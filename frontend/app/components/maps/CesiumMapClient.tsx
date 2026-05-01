"use client";

// Ensure CESIUM_BASE_URL is set before Cesium is imported
if (typeof window !== "undefined") {
  (window as any).CESIUM_BASE_URL = "/cesium/";
}

import React, { useState, useEffect, useRef, useMemo, memo } from "react";
import { Viewer, ImageryLayer, GeoJsonDataSource, Scene } from "resium";
import * as Cesium from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

import { useMapStore } from "../../stores/mapStore";
import { useLayerStore } from "../../stores/layerStore";
import { useUIStore } from "../../stores/uiStore";
import Logger from "../../utils/logger";
import { getApiBase } from "../../utils/apiBase";
import { GeoDataObject, LayerStyle } from "../../models/geodatamodel";
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
} from "../../utils/geoMapHelpers";

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
            className={`font-bold text-sm flex-1 mr-2 ${
              isCollapsed ? "truncate" : "break-words"
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
              className={`w-full object-contain transition-all duration-300 ease-in-out ${
                isImageMaximized ? "max-h-none" : "max-h-50"
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
  title,
}: {
  url: string;
  layerStyle?: LayerStyle;
  title?: string;
}) {
  const [data, setData] = useState<any>(null);
  const dataSourceRef = useRef<Cesium.GeoJsonDataSource | null>(null);

  useEffect(() => {
    const cachedData = geoJSONCache.get(url);
    if (cachedData) {
      setData(cachedData);
      return;
    }

    let requestUrl = url;
    try {
      const testU = new URL(url);
      if (
        (/wfs/i.test(testU.search) ||
          testU.searchParams.get("service")?.toUpperCase() === "WFS") &&
        !testU.searchParams.get("srsName")
      ) {
        testU.searchParams.set("srsName", "EPSG:4326");
        requestUrl = testU.toString();
      }
    } catch (e) {}

    fetchWithCorsProxy(requestUrl, {
      headers: { Accept: "application/json, application/geo+json, */*;q=0.1" },
    })
      .then((res) => {
        if (!res.ok && requestUrl !== url) {
          return fetchWithCorsProxy(url, {
            headers: { Accept: "application/json, application/geo+json, */*;q=0.1" },
          });
        }
        return res;
      })
      .then((res) => res.text())
      .then((text) => {
        try {
          const json = JSON.parse(text);
          geoJSONCache.set(url, json);
          setData(json);
        } catch (e) {
          Logger.error("Failed to parse JSON for GeoJSON layer", e);
        }
      })
      .catch((err) => Logger.error("Failed to load GeoJSON", err));
  }, [url]);

  const strokeColor = useMemo(() => layerStyle?.stroke_color 
    ? Cesium.Color.fromCssColorString(layerStyle.stroke_color).withAlpha(layerStyle.stroke_opacity ?? 1.0)
    : Cesium.Color.BLUE, [layerStyle?.stroke_color, layerStyle?.stroke_opacity]);
    
  const fillColor = useMemo(() => layerStyle?.fill_color
    ? Cesium.Color.fromCssColorString(layerStyle.fill_color).withAlpha(layerStyle.fill_opacity ?? 0.2)
    : Cesium.Color.fromAlpha(Cesium.Color.BLUE, 0.2), [layerStyle?.fill_color, layerStyle?.fill_opacity]);

  // Apply styling reactively across all entities
  const applyStyles = (ds: Cesium.GeoJsonDataSource) => {
    if (!ds || !ds.entities) return;
    const entities = ds.entities.values;
    for (let i = 0; i < entities.length; i++) {
      const entity = entities[i];
      if (entity.polygon) {
        entity.polygon.material = new Cesium.ColorMaterialProperty(fillColor);
        entity.polygon.outlineColor = new Cesium.ConstantProperty(strokeColor);
        entity.polygon.outlineWidth = new Cesium.ConstantProperty(layerStyle?.stroke_weight ?? 2);
      }
      if (entity.polyline) {
        entity.polyline.material = new Cesium.ColorMaterialProperty(strokeColor);
        entity.polyline.width = new Cesium.ConstantProperty(layerStyle?.stroke_weight ?? 2);
      }
      // For point features
      if (entity.position && !entity.polygon && !entity.polyline) {
        // Hide the default giant pin
        if (entity.billboard) {
          entity.billboard.show = new Cesium.ConstantProperty(false);
        }
        // Initialize point graphic if not present
        if (!entity.point) {
          entity.point = new Cesium.PointGraphics();
        }
        entity.point.show = new Cesium.ConstantProperty(true);
        entity.point.color = new Cesium.ConstantProperty(fillColor);
        entity.point.outlineColor = new Cesium.ConstantProperty(strokeColor);
        entity.point.outlineWidth = new Cesium.ConstantProperty(layerStyle?.stroke_weight ?? 1);
        entity.point.pixelSize = new Cesium.ConstantProperty((layerStyle?.point_radius ?? 6) * 2);
        entity.point.heightReference = new Cesium.ConstantProperty(Cesium.HeightReference.CLAMP_TO_GROUND);
      }
    }
  };

  useEffect(() => {
    if (dataSourceRef.current) {
      applyStyles(dataSourceRef.current);
    }
  }, [fillColor, strokeColor, layerStyle]);

  if (!data) return null;

  return (
    <GeoJsonDataSource
      ref={(e) => {
        if (e && e.cesiumElement) {
          dataSourceRef.current = e.cesiumElement;
        }
      }}
      data={data}
      name={title}
      clampToGround={true}
      onLoad={(ds) => {
        applyStyles(ds);
      }}
    />
  );
});

export default function CesiumMapClient() {
  const viewerRef = useRef<Cesium.Viewer | null>(null);
  const basemap = useMapStore((state) => state.basemap);
  const layers = useLayerStore((state) => state.layers);

  const visibleLayers = useMemo(() => layers.filter((l) => l.visible), [layers]);

  // Provider for the basemap
  const basemapProvider = useMemo(() => {
    // Basic substitution for cartocdn like {s}.basemaps.cartocdn.com
    let parsedUrl = basemap.url;
    let subdomains = ["a", "b", "c"];
    return new Cesium.UrlTemplateImageryProvider({
      url: parsedUrl,
      subdomains,
      credit: new Cesium.Credit(basemap.attribution.replace(/<[^>]+>/g, " ")),
    });
  }, [basemap]);

  // Handle bounding box zoom for non-tiled or new layers
  const zoomedLayers = useRef<Set<string | number>>(new Set());
  useEffect(() => {
    if (!viewerRef.current) return;
    const viewer = viewerRef.current;

    visibleLayers.forEach((layer) => {
      if (zoomedLayers.current.has(layer.id)) return;

      if (layer.bounding_box) {
        let bounds: [number, number, number, number] | null = null;

        if (typeof layer.bounding_box === "string" && layer.bounding_box.includes("POLYGON")) {
          const match = layer.bounding_box.match(/POLYGON\(\((.+?)\)\)/);
          if (match) {
            const coords = match[1]
              .split(",")
              .map((pair) => pair.trim().split(" ").map(Number))
              .filter(([lng, lat]) => !isNaN(lng) && !isNaN(lat));

            if (coords.length > 0) {
              const lats = coords.map(([lng, lat]) => lat);
              const lngs = coords.map(([lng, lat]) => lng);
              bounds = [Math.min(...lngs), Math.min(...lats), Math.max(...lngs), Math.max(...lats)];
            }
          }
        } else if (Array.isArray(layer.bounding_box) && layer.bounding_box.length >= 4) {
          const [minX, minY, maxX, maxY] = layer.bounding_box;
          bounds = [minX, minY, maxX, maxY]; // Ensure standard West, South, East, North
        }

        if (bounds) {
          const [west, south, east, north] = bounds;
          const rectangle = Cesium.Rectangle.fromDegrees(west, south, east, north);
          viewer.camera.flyTo({
            destination: rectangle,
            duration: 1.5,
          });
          zoomedLayers.current.add(layer.id);
        }
      }
    });
  }, [visibleLayers]);

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
          }
        }}
        terrainProvider={Cesium.createWorldTerrainAsync()}
        baseLayerPicker={false}
        geocoder={false}
        homeButton={true}
        infoBox={false}
        sceneModePicker={true}
        navigationHelpButton={false}
        animation={false}
        timeline={false}
        imageryProvider={false}
      >
        {/* Basemap */}
        {basemapProvider && <ImageryLayer imageryProvider={basemapProvider} />}

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
          } else if (
            layer.layer_type?.toUpperCase() === "WFS" ||
            layer.layer_type?.toUpperCase() === "UPLOADED" ||
            layer.data_link.toLowerCase().includes("json")
          ) {
            return (
              <CesiumGeoJSONLayer
                key={layer.id}
                url={layer.data_link}
                title={layer.title || layer.name}
                layerStyle={layer.style}
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
    </div>
  );
}
