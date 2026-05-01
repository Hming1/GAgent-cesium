import Logger from "./logger";
import { getApiBase } from "./apiBase";

// ============================================
// GeoJSON CACHE IMPLEMENTATION
// ============================================

export interface CacheEntry {
  data: any;
  timestamp: number;
  size: number;
}

export class GeoJSONCache {
  private cache = new Map<string, CacheEntry>();
  private maxSize = 50 * 1024 * 1024; // 50MB cache limit
  private maxAge = 30 * 60 * 1000; // 30 minutes
  private currentSize = 0;

  set(url: string, data: any): void {
    const size = JSON.stringify(data).length;
    
    while (this.currentSize + size > this.maxSize && this.cache.size > 0) {
      this.evictOldest();
    }

    const entry: CacheEntry = {
      data,
      timestamp: Date.now(),
      size,
    };
    
    this.cache.set(url, entry);
    this.currentSize += size;
    
    Logger.log(`[GeoJSONCache] Cached ${url} (${(size / 1024).toFixed(2)} KB). Cache size: ${(this.currentSize / 1024 / 1024).toFixed(2)} MB`);
  }

  get(url: string): any | null {
    const entry = this.cache.get(url);
    if (!entry) return null;

    if (Date.now() - entry.timestamp > this.maxAge) {
      this.delete(url);
      return null;
    }

    Logger.log(`[GeoJSONCache] Cache HIT for ${url}`);
    return entry.data;
  }

  delete(url: string): void {
    const entry = this.cache.get(url);
    if (entry) {
      this.cache.delete(url);
      this.currentSize -= entry.size;
      Logger.log(`[GeoJSONCache] Deleted ${url}. Cache size: ${(this.currentSize / 1024 / 1024).toFixed(2)} MB`);
    }
  }

  private evictOldest(): void {
    let oldest: [string, CacheEntry] | null = null;
    
    for (const [url, entry] of this.cache.entries()) {
      if (!oldest || entry.timestamp < oldest[1].timestamp) {
        oldest = [url, entry];
      }
    }
    
    if (oldest) {
      this.delete(oldest[0]);
      Logger.log(`[GeoJSONCache] Evicted oldest entry: ${oldest[0]}`);
    }
  }

  clear(): void {
    this.cache.clear();
    this.currentSize = 0;
    Logger.log('[GeoJSONCache] Cache cleared');
  }

  getCacheStats(): { entries: number; size: number; maxSize: number } {
    return {
      entries: this.cache.size,
      size: this.currentSize,
      maxSize: this.maxSize,
    };
  }
}

// Global cache instance
export const geoJSONCache = new GeoJSONCache();

if (typeof window !== "undefined") {
  (window as any).geoJSONCache = geoJSONCache;
}

// ============================================
// CORS PROXY HELPER
// ============================================

export function isExternalUrl(url: string): boolean {
  try {
    const targetUrl = new URL(url);
    const currentOrigin =
      typeof window !== "undefined" ? window.location.origin : "";
    const apiBase = getApiBase();
    const apiOrigin = apiBase.startsWith("http") ? new URL(apiBase).origin : "";

    return (
      targetUrl.origin !== currentOrigin &&
      targetUrl.origin !== apiOrigin &&
      !url.startsWith("/")
    );
  } catch {
    return false;
  }
}

export function getProxiedUrl(originalUrl: string, srsName?: string): string {
  const apiBase = getApiBase();
  const params = new URLSearchParams({ url: originalUrl });
  if (srsName) {
    params.set("srsName", srsName);
  }
  return `${apiBase}/proxy/geojson?${params.toString()}`;
}

export function getProxiedImageUrl(originalUrl: string): string {
  const apiBase = getApiBase();
  const params = new URLSearchParams({ url: originalUrl });
  return `${apiBase}/proxy/image?${params.toString()}`;
}

export async function fetchWithCorsProxy(
  url: string,
  options?: RequestInit,
): Promise<Response> {
  const isExternal = isExternalUrl(url);

  try {
    const res = await fetch(url, options);
    if (res.ok) return res;
    return res;
  } catch (err) {
    if (isExternal && err instanceof TypeError) {
      Logger.log(
        `[CORS Proxy] Direct fetch failed for external URL, trying proxy: ${url}`,
      );

      let srsName: string | undefined;
      try {
        const testU = new URL(url);
        srsName = testU.searchParams.get("srsName") || undefined;
      } catch {
        /* ignore */
      }

      const proxiedUrl = getProxiedUrl(url, srsName);
      return fetch(proxiedUrl, {
        headers: {
          Accept: "application/json, application/geo+json, */*;q=0.1",
        },
      });
    }
    throw err;
  }
}

// ============================================
// OGC PARSERS
// ============================================

export function parseWMSUrl(access_url: string) {
  try {
    const urlObj = new URL(access_url);
    const baseUrl = `${urlObj.origin}${urlObj.pathname}`;
    const params = urlObj.searchParams;
    return {
      baseUrl,
      layers: params.get("layers") || "",
      format: params.get("format") || "image/png",
      transparent: params.get("transparent")
        ? params.get("transparent") === "true"
        : true,
    };
  } catch (err) {
    Logger.error("Error parsing WMS URL:", err);
    return {
      baseUrl: access_url,
      layers: "",
      format: "image/png",
      transparent: true,
    };
  }
}

export function parseWMTSUrl(access_url: string) {
  try {
    const urlObj = new URL(access_url);
    const baseUrl = `${urlObj.origin}${urlObj.pathname}`;
    const originalParams = urlObj.searchParams;

    const versionParam =
      originalParams.get("version") || originalParams.get("VERSION") || "";
    let version = versionParam;

    let layerName = originalParams.get("layer") || originalParams.get("LAYER");

    if (!layerName) {
      const pathParts = urlObj.pathname.split("/");
      const restIndex = pathParts.indexOf("rest");
      if (restIndex !== -1 && restIndex + 1 < pathParts.length) {
        layerName = pathParts[restIndex + 1];
      }
    }
    if (!layerName) {
      const colonSegment = urlObj.pathname
        .split("/")
        .find((p) => p.includes(":"));
      if (colonSegment) layerName = colonSegment;
    }
    if (
      layerName &&
      (layerName.toLowerCase() === "default" || layerName.includes("{"))
    ) {
      layerName = "";
    }

    if (!layerName) {
      Logger.warn("Could not extract layer name from WMTS URL:", access_url);
      return {
        wmtsLegendUrl: "",
        wmsLegendUrl: "",
        layerName: "",
        originalUrl: access_url,
        version: version || undefined,
      };
    }

    let workspace = "";
    let finalLayerName = layerName;
    if (layerName.includes(":")) {
      [workspace, finalLayerName] = layerName.split(":");
    }

    const pathParts = urlObj.pathname.split("/").filter(Boolean);
    const geoserverIdx = pathParts.indexOf("geoserver");
    const geoserverBase =
      geoserverIdx !== -1
        ? `${urlObj.origin}/${pathParts.slice(0, geoserverIdx + 1).join("/")}`
        : `${urlObj.origin}`;
    const wmtsKvpBase = `${geoserverBase}/gwc/service/wmts`;
    const wmsBaseUrl = `${geoserverBase}/wms`;
    const wmsLegendParams = new URLSearchParams({
      service: "WMS",
      version: "1.1.0",
      request: "GetLegendGraphic",
      format: "image/png",
      layer: layerName,
    });
    const wmsLegendUrl = `${wmsBaseUrl}?${wmsLegendParams.toString()}`;

    return {
      wmtsLegendUrl: "",
      wmsLegendUrl,
      layerName: finalLayerName,
      workspace,
      fullLayerName: workspace
        ? `${workspace}:${finalLayerName}`
        : finalLayerName,
      originalUrl: access_url,
      wmtsKvpBase,
      version: version || undefined,
    };
  } catch (err) {
    Logger.error("Error parsing WMTS URL:", err);
    return {
      wmtsLegendUrl: "",
      wmsLegendUrl: "",
      layerName: "",
      originalUrl: access_url,
    };
  }
}

export function buildWMTSKvpTemplate(
  base: string,
  fullLayerName: string,
  tileMatrixSet: string,
  format: string = "image/png",
  version: string = "1.0.0",
) {
  return `${base}?service=WMTS&version=${encodeURIComponent(version)}&request=GetTile&layer=${encodeURIComponent(fullLayerName)}&style=&tilematrixset=${encodeURIComponent(tileMatrixSet)}&format=${encodeURIComponent(format)}&tilematrix=${encodeURIComponent(tileMatrixSet)}:{z}&tilerow={y}&tilecol={x}`;
}

export function isWebMercatorMatrixSet(name: string | undefined | null): boolean {
  if (!name) return false;
  return /3857|900913|googlemapscompatible|google|web ?mercator|mercatorquad/i.test(
    name,
  );
}

export function pickWebMercatorMatrixSet(candidateSets: string[]): string | undefined {
  if (!candidateSets || !candidateSets.length) return undefined;
  let chosen = candidateSets.find((s) => /3857/.test(s));
  if (chosen) return chosen;
  chosen = candidateSets.find((s) => /900913|google|mercator/i.test(s));
  return chosen;
}

export function parseWCSUrl(access_url: string) {
  try {
    const urlObj = new URL(access_url);
    const baseUrl = `${urlObj.origin}${urlObj.pathname}`;
    const params = urlObj.searchParams;
    const coverageId = params.get("coverageId") || params.get("coverage") || "";
    if (!coverageId) {
      Logger.warn("Could not extract coverageId from WCS URL:", access_url);
    }
    let wmsBaseUrl = baseUrl;
    if (wmsBaseUrl.endsWith("/wcs")) {
      wmsBaseUrl = wmsBaseUrl.slice(0, -4) + "/wms";
    } else if (wmsBaseUrl.endsWith("/ows")) {
      wmsBaseUrl = wmsBaseUrl.replace(/\/ows$/, "/wms");
    } else if (!wmsBaseUrl.endsWith("/wms")) {
      wmsBaseUrl = wmsBaseUrl + "/wms";
    }
    const legendParams = new URLSearchParams({
      service: "WMS",
      request: "GetLegendGraphic",
      version: "1.1.0",
      format: "image/png",
      layer: coverageId,
    });
    const legendUrl = `${wmsBaseUrl}?${legendParams.toString()}`;
    return {
      baseUrl: wmsBaseUrl,
      layers: coverageId,
      format: "image/png",
      transparent: true,
      legendUrl,
      originalUrl: access_url,
    };
  } catch (err) {
    Logger.error("Error parsing WCS URL:", err);
    return {
      baseUrl: access_url,
      layers: "",
      format: "image/png",
      transparent: true,
      legendUrl: "",
      originalUrl: access_url,
    };
  }
}
