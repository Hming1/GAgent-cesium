// stores/mapStore.ts
import { create } from "zustand";
import Logger from "../utils/logger";
import { getApiBase } from "../utils/apiBase";
import { DEFAULT_BASEMAP, getBasemapKey, getBasemapLabel, getFallbackBasemap, type BasemapInfo, type BasemapKey } from "../utils/basemaps";

type MapRecord = {
  id: string;
  name: string;
  description?: string | null;
};

type MapState = {
  basemap: BasemapInfo;
  failedBasemaps: BasemapKey[];
  basemapNotice: { message: string; retryKey: BasemapKey } | null;
  reportBasemapFailure: (source: BasemapInfo) => void;
  maps: MapRecord[];
  currentMapId: string | null;
  setBasemap: (basemap: BasemapInfo) => void;
  setMaps: (maps: MapRecord[]) => void;
  setCurrentMapId: (mapId: string | null) => void;
  loadMaps: () => Promise<void>;
  ensureDefaultMap: () => Promise<void>;
  createMap: (name: string, description?: string | null) => Promise<MapRecord | null>;
  clearMaps: () => void;
};

type MapApiRecord = {
  id: string;
  name: string;
  description?: string | null;
};

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    throw new Error(`请求失败：${res.status}`);
  }
  return (await res.json()) as T;
}

export const useMapStore = create<MapState>((set) => ({
  basemap: DEFAULT_BASEMAP,
  failedBasemaps: [],
  basemapNotice: null,
  maps: [],
  currentMapId: null,
  setBasemap: (basemap) => set({ basemap, failedBasemaps: [], basemapNotice: null }),
  reportBasemapFailure: (source) => set((state) => {
    if (state.basemap !== source) return state;
    const failedKey = getBasemapKey(source);
    if (state.failedBasemaps.includes(failedKey)) return state;
    const failedBasemaps = [...state.failedBasemaps, failedKey];
    const retryKey = state.basemapNotice?.retryKey ?? failedKey;
    const next = getFallbackBasemap(retryKey, failedBasemaps);
    return {
      basemap: next ?? source,
      failedBasemaps,
      basemapNotice: {
        retryKey,
        message: next
          ? getBasemapLabel(failedKey) + "加载失败，已切换到" + getBasemapLabel(getBasemapKey(next)) + "。"
          : "当前底图及备用底图均加载失败，请检查网络后重试。",
      },
    };
  }),
  setMaps: (maps) =>
    set((state) => ({
      maps,
      currentMapId:
        state.currentMapId && maps.some((m) => m.id === state.currentMapId)
          ? state.currentMapId
          : maps[0]?.id ?? null,
    })),
  setCurrentMapId: (mapId) => set({ currentMapId: mapId }),
  loadMaps: async () => {
    try {
      const apiBase = getApiBase();
      const records = await fetchJson<MapApiRecord[]>(`${apiBase}/maps/`);
      const maps = records.map((record) => ({
        id: record.id,
        name: record.name,
        description: record.description ?? null,
      }));
      set((state) => ({
        maps,
        currentMapId:
          state.currentMapId && maps.some((m) => m.id === state.currentMapId)
            ? state.currentMapId
            : maps[0]?.id ?? null,
      }));
    } catch (err) {
      Logger.warn("Failed to load maps:", err);
    }
  },
  ensureDefaultMap: async () => {
    try {
      const apiBase = getApiBase();
      const records = await fetchJson<MapApiRecord[]>(`${apiBase}/maps/`);
      if (records.length > 0) {
        set(() => ({
          maps: records,
          currentMapId: records[0]?.id ?? null,
        }));
        return;
      }

      const created = await fetchJson<MapApiRecord>(`${apiBase}/maps/`, {
        method: "POST",
        body: JSON.stringify({
          name: "My Map",
          description: "Default map",
        }),
      });
      set(() => ({
        maps: [created],
        currentMapId: created.id,
      }));
    } catch (err) {
      Logger.warn("Failed to ensure default map:", err);
    }
  },
  createMap: async (name: string, description?: string | null) => {
    try {
      const apiBase = getApiBase();
      const created = await fetchJson<MapApiRecord>(`${apiBase}/maps/`, {
        method: "POST",
        body: JSON.stringify({ name, description }),
      });
      const record: MapRecord = {
        id: created.id,
        name: created.name,
        description: created.description ?? null,
      };
      set((state) => ({
        maps: [...state.maps, record],
        currentMapId: record.id,
      }));
      return record;
    } catch (err) {
      Logger.warn("Failed to create map:", err);
    }
    return null;
  },
  clearMaps: () => set({ maps: [], currentMapId: null }),
}));

// Expose store to window for E2E testing
if (typeof window !== "undefined") {
  (window as any).useMapStore = useMapStore;
  console.log("[MapStore] Exposed to window for testing");
}
