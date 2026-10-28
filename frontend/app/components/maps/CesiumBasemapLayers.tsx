"use client";

import { useEffect, useMemo } from "react";
import { ImageryLayer } from "resium";
import * as Cesium from "cesium";
import { useMapStore } from "../../stores/mapStore";
import { DEFAULT_BASEMAP_KEY, getBasemap, getTianDiTuToken } from "../../utils/basemaps";

const FIRST_TILE_TIMEOUT_MS = 12000;

function injectRuntimeTiandituToken(url: string): string {
  const token = getTianDiTuToken();
  if (!token || !url.includes("tianditu.gov.cn")) return url;
  return url
    .replace("{tiandituToken}", encodeURIComponent(token))
    .replace(/([?&]tk=)(?:&|$)/, `$1${encodeURIComponent(token)}`);
}

/** Keep the selected source, overlays and failure state together. */
export default function CesiumBasemapLayers() {
  const basemap = useMapStore((state) => state.basemap);
  const setBasemap = useMapStore((state) => state.setBasemap);
  const reportFailure = useMapStore((state) => state.reportBasemapFailure);

  useEffect(() => {
    const token = getTianDiTuToken();
    const isTianditu = (basemap.key ?? DEFAULT_BASEMAP_KEY).startsWith("tianditu-") || basemap.url.includes("tianditu.gov.cn");
    if (!isTianditu) return;
    if (!token) {
      setBasemap(getBasemap("amap-standard"));
      return;
    }
    if (/[?&]tk=(?:&|$)/.test(basemap.url) || basemap.url.includes("{tiandituToken}")) {
      setBasemap(getBasemap(basemap.key ?? DEFAULT_BASEMAP_KEY));
    }
  }, [basemap, setBasemap]);

  const providers = useMemo(
    () => [basemap, ...(basemap.overlays ?? [])].map((source) =>
      new Cesium.UrlTemplateImageryProvider({
        url: injectRuntimeTiandituToken(source.url).replace("{r}", ""),
        subdomains: source.subdomains,
        minimumLevel: source.minimumLevel,
        maximumLevel: source.maximumLevel,
        credit: new Cesium.Credit(
          (source.attribution ?? basemap.attribution ?? "").replace(/<[^>]+>/g, " "),
        ),
      }),
    ),
    [basemap],
  );

  useEffect(() => {
    let active = true;
    const cleanups = providers.map((provider) => {
      let loaded = false;
      let watchdog: ReturnType<typeof setTimeout> | undefined;
      const clearWatchdog = () => {
        if (watchdog !== undefined) clearTimeout(watchdog);
        watchdog = undefined;
      };
      const fail = () => {
        clearWatchdog();
        if (active && !loaded) reportFailure(basemap);
      };
      const originalRequestImage = provider.requestImage;
      provider.requestImage = (...args) => {
        const result = originalRequestImage.apply(provider, args);
        // Undefined means Cesium's scheduler deferred the request.
        if (!result) return result;
        if (!loaded && watchdog === undefined) {
          watchdog = setTimeout(fail, FIRST_TILE_TIMEOUT_MS);
        }
        return Promise.resolve(result).then(
          (image) => {
            loaded = true;
            clearWatchdog();
            return image;
          },
          (err) => {
            // Let errorEvent decide retries; watchdog still covers stalls.
            throw err;
          },
        );
      };
      const removeErrorListener = provider.errorEvent.addEventListener((error: Cesium.TileProviderError) => {
        if (!active) return;
        // Retry transient failures before giving up on a tile ( once Cesium gives
        // up on a parent tile it stops subdividing into finer zoom levels).
        const maxRetries = loaded ? 2 : 1;
        error.retry = error.timesRetried < maxRetries;
        if (!error.retry) fail();
      });
      return () => {
        clearWatchdog();
        removeErrorListener();
        provider.requestImage = originalRequestImage;
      };
    });
    return () => {
      active = false;
      cleanups.forEach((cleanup) => cleanup());
    };
  }, [basemap, providers, reportFailure]);

  return (
    <>
      {providers.map((provider, index) => (
        <ImageryLayer key={basemap.url + ":" + index} imageryProvider={provider} />
      ))}
    </>
  );
}
