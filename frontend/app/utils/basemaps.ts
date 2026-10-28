export type BasemapTileSource = {
  url: string;
  attribution?: string;
  subdomains?: string[];
  minimumLevel?: number;
  maximumLevel?: number;
};

export type BasemapInfo = BasemapTileSource & {
  key?: BasemapKey;
  overlays?: BasemapTileSource[];
};

export type BasemapKey =
  | "osm"
  | "carto-positron"
  | "carto-dark"
  | "amap-standard"
  | "amap-satellite"
  | "amap-hybrid"
  | "google-satellite"
  | "google-hybrid"
  | "google-terrain"
  | "tianditu-vector"
  | "tianditu-satellite"
  | "tianditu-hybrid";

export type BasemapOption = {
  key: BasemapKey;
  label: string;
  disabled?: boolean;
  disabledReason?: string;
};

const cartoAttribution =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, &copy; <a href="https://carto.com/attribution">CARTO</a>';

export function getTianDiTuToken(): string {
  const runtimeToken =
    typeof window !== "undefined"
      ? window.__RUNTIME_CONFIG__?.NEXT_PUBLIC_TIANDITU_TOKEN
      : undefined;
  return (runtimeToken ?? process.env.NEXT_PUBLIC_TIANDITU_TOKEN ?? "").trim();
}

const tianDiTuSubdomains = ["0", "1", "2", "3", "4", "5", "6", "7"];

const tianDiTuUrl = (layer: string) =>
  `https://t{s}.tianditu.gov.cn/DataServer?T=${layer}&x={x}&y={y}&l={z}&tk={tiandituToken}`;

/** Preferred default: Tianditu vector (requires NEXT_PUBLIC_TIANDITU_TOKEN). */
export const DEFAULT_BASEMAP_KEY: BasemapKey = "tianditu-vector";

/** Used when Tianditu is selected/defaulted but no token is available. */
const TOKENLESS_FALLBACK_KEY: BasemapKey = "amap-standard";

export const BASEMAPS: Record<BasemapKey, BasemapInfo> = {
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution:
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    subdomains: ["a", "b", "c"],
  },
  "carto-positron": {
    url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    attribution: cartoAttribution,
    subdomains: ["a", "b", "c", "d"],
  },
  "carto-dark": {
    url: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
    attribution: cartoAttribution,
    subdomains: ["a", "b", "c", "d"],
  },
  "amap-standard": {
    // style=8 = road + labels. Host wprd0{s} with subdomains 1-4.
    url: "https://wprd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scl=1&style=8&x={x}&y={y}&z={z}",
    attribution: "&copy; 高德地图",
    subdomains: ["1", "2", "3", "4"],
  },
  "amap-satellite": {
    url: "https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
    attribution: "&copy; 高德地图",
    subdomains: ["1", "2", "3", "4"],
  },
  "amap-hybrid": {
    url: "https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}",
    attribution: "&copy; 高德地图",
    subdomains: ["1", "2", "3", "4"],
    overlays: [
      {
        url: "https://webst0{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}",
        subdomains: ["1", "2", "3", "4"],
      },
    ],
  },
  "google-satellite": {
    url: "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
    attribution: "&copy; Google",
  },
  "google-hybrid": {
    url: "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
    attribution: "&copy; Google",
  },
  "google-terrain": {
    url: "https://mt1.google.com/vt/lyrs=p&x={x}&y={y}&z={z}",
    attribution: "&copy; Google",
  },
  "tianditu-vector": {
    url: tianDiTuUrl("vec_w"),
    attribution: "&copy; 天地图",
    subdomains: tianDiTuSubdomains,
    overlays: [
      {
        url: tianDiTuUrl("cva_w"),
        subdomains: tianDiTuSubdomains,
      },
    ],
  },
  "tianditu-satellite": {
    url: tianDiTuUrl("img_w"),
    attribution: "&copy; 天地图",
    subdomains: tianDiTuSubdomains,
  },
  "tianditu-hybrid": {
    url: tianDiTuUrl("img_w"),
    attribution: "&copy; 天地图",
    subdomains: tianDiTuSubdomains,
    overlays: [
      {
        url: tianDiTuUrl("cia_w"),
        subdomains: tianDiTuSubdomains,
      },
    ],
  },
};

export const BASEMAP_OPTIONS: BasemapOption[] = [
  { key: "osm", label: "OpenStreetMap 标准底图" },
  { key: "carto-positron", label: "Carto 浅色底图" },
  { key: "carto-dark", label: "Carto 深色底图" },
  { key: "amap-standard", label: "高德标准地图" },
  { key: "amap-satellite", label: "高德卫星影像" },
  { key: "amap-hybrid", label: "高德卫星混合图" },
  { key: "google-satellite", label: "Google 卫星影像" },
  { key: "google-hybrid", label: "Google 混合图" },
  { key: "google-terrain", label: "Google 地形图" },
  {
    key: "tianditu-vector",
    label: "天地图矢量地图",
    disabled: true,
    disabledReason: "需配置 NEXT_PUBLIC_TIANDITU_TOKEN",
  },
  {
    key: "tianditu-satellite",
    label: "天地图卫星影像",
    disabled: true,
    disabledReason: "需配置 NEXT_PUBLIC_TIANDITU_TOKEN",
  },
  {
    key: "tianditu-hybrid",
    label: "天地图卫星混合图",
    disabled: true,
    disabledReason: "需配置 NEXT_PUBLIC_TIANDITU_TOKEN",
  },
];

export function getBasemapOptions(): BasemapOption[] {
  return BASEMAP_OPTIONS.map((option) => ({
    ...option,
    disabled: option.key.startsWith("tianditu-") && !getTianDiTuToken(),
  }));
}

function isTiandituKey(key: string): boolean {
  return key.startsWith("tianditu-");
}

export function getBasemap(key: string): BasemapInfo {
  let resolvedKey: BasemapKey = Object.prototype.hasOwnProperty.call(BASEMAPS, key)
    ? (key as BasemapKey)
    : DEFAULT_BASEMAP_KEY;

  // Never start / resolve to Tianditu without a token — that yields blank tiles.
  if (isTiandituKey(resolvedKey) && !getTianDiTuToken()) {
    resolvedKey = TOKENLESS_FALLBACK_KEY;
  }

  const source = BASEMAPS[resolvedKey];
  const minimumLevel = isTiandituKey(resolvedKey) ? 1 : 0;
  const maximumLevel =
    resolvedKey === "osm"
      ? 19
      : resolvedKey.startsWith("carto-") || resolvedKey.startsWith("google-")
        ? 20
        : 18;
  const resolveSource = (tile: BasemapTileSource): BasemapTileSource => ({
    ...tile,
    url: tile.url.replace("{tiandituToken}", encodeURIComponent(getTianDiTuToken())),
    minimumLevel,
    maximumLevel,
  });
  return {
    ...resolveSource(source),
    key: resolvedKey,
    overlays: source.overlays?.map(resolveSource),
  };
}

export function getBasemapKey(basemap: BasemapInfo): BasemapKey {
  return (
    basemap.key ??
    BASEMAP_OPTIONS.find((option) => getBasemap(option.key).url === basemap.url)?.key ??
    DEFAULT_BASEMAP_KEY
  );
}

export function getBasemapLabel(key: BasemapKey): string {
  return BASEMAP_OPTIONS.find((option) => option.key === key)?.label ?? key;
}

export function getFallbackBasemap(
  original: BasemapKey,
  failed: BasemapKey[],
): BasemapInfo | undefined {
  const choices: BasemapKey[] =
    original.includes("satellite") || original.includes("hybrid")
      ? ["google-satellite", "tianditu-satellite", "amap-satellite", "carto-positron", "osm"]
      : ["carto-positron", "osm", "google-terrain", "tianditu-vector", "amap-standard"];
  const available = getBasemapOptions().filter((option) => !option.disabled);
  const next = choices.find(
    (key) =>
      !failed.includes(key) &&
      key !== original &&
      available.some((option) => option.key === key) &&
      Object.prototype.hasOwnProperty.call(BASEMAPS, key),
  );
  return next ? getBasemap(next) : undefined;
}

export const DEFAULT_BASEMAP = getBasemap(DEFAULT_BASEMAP_KEY);
