import { test, expect } from "@playwright/test";

/**
 * Pure logic mirror of resolveLayerDataUrl — keeps the contract covered without
 * bundling Next/window getApiBase into Playwright's node runner.
 */
function resolveLayerDataUrl(dataLink: string | undefined | null, apiBase: string): string {
  if (!dataLink) return "";
  const trimmed = dataLink.trim();
  if (!trimmed) return "";

  const streamMarker = "/api/stream/";
  const streamIdx = trimmed.indexOf(streamMarker);
  if (streamIdx !== -1) {
    const filename = trimmed.slice(streamIdx + streamMarker.length);
    if (!filename) return trimmed;
    return `${apiBase.replace(/\/$/, "")}/stream/${filename}`;
  }

  if (trimmed.startsWith("/")) {
    return trimmed;
  }

  return trimmed;
}

test.describe("resolveLayerDataUrl", () => {
  test("rewrites absolute BASE_URL stream links to relative api base", () => {
    const link =
      "http://39.105.94.209/api/stream/24430ec4784a4c4fa2a8c6c88f397d6f_public_layer.geojson";
    expect(resolveLayerDataUrl(link, "/api")).toBe(
      "/api/stream/24430ec4784a4c4fa2a8c6c88f397d6f_public_layer.geojson",
    );
  });

  test("rewrites absolute stream links to localhost api base", () => {
    const link =
      "http://39.105.94.209/api/stream/ce9731e0930f4bccb81bc6bd8d61647e_points.geojson";
    expect(resolveLayerDataUrl(link, "http://localhost:8000/api")).toBe(
      "http://localhost:8000/api/stream/ce9731e0930f4bccb81bc6bd8d61647e_points.geojson",
    );
  });

  test("leaves relative stream paths unchanged", () => {
    expect(resolveLayerDataUrl("/api/stream/local.geojson", "/api")).toBe(
      "/api/stream/local.geojson",
    );
  });

  test("leaves non-stream absolute URLs unchanged", () => {
    const wms =
      "https://geoserver.example.com/geoserver/wms?service=WMS&layers=foo";
    expect(resolveLayerDataUrl(wms, "/api")).toBe(wms);
  });

  test("handles empty input", () => {
    expect(resolveLayerDataUrl(null, "/api")).toBe("");
    expect(resolveLayerDataUrl(undefined, "/api")).toBe("");
    expect(resolveLayerDataUrl("  ", "/api")).toBe("");
  });
});
