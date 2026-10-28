import { create } from "zustand";
import { getApiBase } from "../utils/apiBase";

export type InefficientType =
  | "idle_vacant"
  | "industrial"
  | "commercial"
  | "residential";

export type FieldMapping = {
  far: string;
  building_density: string;
  idle_years: string;
  tax_output: string;
  land_use: string;
  enterprise_tax_field: string;
};

export type TypeThresholds = {
  max_far: number;
  max_building_density: number;
  min_idle_years: number;
  min_tax_output: number;
  near_zero_far: number;
  near_zero_density: number;
};

export type ThresholdBundle = {
  idle_vacant: TypeThresholds;
  industrial: TypeThresholds;
  commercial: TypeThresholds;
  residential: TypeThresholds;
};

export type TypeSummary = {
  count: number;
  area_sqm: number;
};

export type AnalyzeSummary = {
  total: number;
  matched: number;
  by_type: Record<string, TypeSummary>;
  area_stats: Record<string, number>;
};

export type InefficientPresets = {
  field_mapping: FieldMapping;
  thresholds: ThresholdBundle;
  enabled_types: InefficientType[];
  land_use_hints: Record<string, string[]>;
  type_labels: Record<string, string>;
  type_colors: Record<string, string>;
};

type InefficientSpaceState = {
  parcelLayerId: string | null;
  poiLayerId: string | null;
  enterpriseLayerId: string | null;
  fieldMapping: FieldMapping;
  thresholds: ThresholdBundle;
  enabledTypes: InefficientType[];
  includeNonMatch: boolean;
  resultName: string;
  presets: InefficientPresets | null;
  summary: AnalyzeSummary | null;
  lastResultLayerId: string | null;
  loading: boolean;
  error: string | null;
  setParcelLayerId: (id: string | null) => void;
  setPoiLayerId: (id: string | null) => void;
  setEnterpriseLayerId: (id: string | null) => void;
  setFieldMapping: (mapping: Partial<FieldMapping>) => void;
  setThreshold: (
    type: InefficientType,
    key: keyof TypeThresholds,
    value: number,
  ) => void;
  toggleEnabledType: (type: InefficientType) => void;
  setIncludeNonMatch: (value: boolean) => void;
  setResultName: (name: string) => void;
  setSummary: (summary: AnalyzeSummary | null) => void;
  setLastResultLayerId: (id: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  loadPresets: () => Promise<void>;
};

const defaultThresholds = (): TypeThresholds => ({
  max_far: 0.8,
  max_building_density: 0.3,
  min_idle_years: 2,
  min_tax_output: 50,
  near_zero_far: 0.05,
  near_zero_density: 0.05,
});

const defaultFieldMapping = (): FieldMapping => ({
  far: "far",
  building_density: "building_density",
  idle_years: "idle_years",
  tax_output: "tax_output",
  land_use: "land_use",
  enterprise_tax_field: "tax_output",
});

export const DEFAULT_TYPE_COLORS: Record<string, string> = {
  idle_vacant: "#7f8c8d",
  industrial: "#c0392b",
  commercial: "#e67e22",
  residential: "#8e44ad",
  efficient: "#27ae60",
};

export const DEFAULT_TYPE_LABELS: Record<string, string> = {
  idle_vacant: "闲置空地",
  industrial: "工业低效",
  commercial: "商业低效",
  residential: "居住低效",
  efficient: "非低效",
};

export const useInefficientSpaceStore = create<InefficientSpaceState>((set, get) => ({
  parcelLayerId: null,
  poiLayerId: null,
  enterpriseLayerId: null,
  fieldMapping: defaultFieldMapping(),
  thresholds: {
    idle_vacant: defaultThresholds(),
    industrial: {
      ...defaultThresholds(),
      max_far: 1.0,
      max_building_density: 0.35,
      min_tax_output: 80,
    },
    commercial: {
      ...defaultThresholds(),
      max_far: 1.5,
      max_building_density: 0.4,
      min_tax_output: 120,
    },
    residential: {
      ...defaultThresholds(),
      max_far: 1.2,
      max_building_density: 0.3,
      min_tax_output: 40,
    },
  },
  enabledTypes: ["idle_vacant", "industrial", "commercial", "residential"],
  includeNonMatch: false,
  resultName: "低效空间判别结果",
  presets: null,
  summary: null,
  lastResultLayerId: null,
  loading: false,
  error: null,
  setParcelLayerId: (id) => set({ parcelLayerId: id }),
  setPoiLayerId: (id) => set({ poiLayerId: id }),
  setEnterpriseLayerId: (id) => set({ enterpriseLayerId: id }),
  setFieldMapping: (mapping) =>
    set({ fieldMapping: { ...get().fieldMapping, ...mapping } }),
  setThreshold: (type, key, value) =>
    set({
      thresholds: {
        ...get().thresholds,
        [type]: { ...get().thresholds[type], [key]: value },
      },
    }),
  toggleEnabledType: (type) => {
    const current = get().enabledTypes;
    set({
      enabledTypes: current.includes(type)
        ? current.filter((item) => item !== type)
        : [...current, type],
    });
  },
  setIncludeNonMatch: (value) => set({ includeNonMatch: value }),
  setResultName: (name) => set({ resultName: name }),
  setSummary: (summary) => set({ summary }),
  setLastResultLayerId: (id) => set({ lastResultLayerId: id }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  loadPresets: async () => {
    try {
      const resp = await fetch(`${getApiBase()}/inefficient-space/presets`);
      if (!resp.ok) throw new Error(`加载预设失败 (${resp.status})`);
      const data = (await resp.json()) as InefficientPresets;
      set({
        presets: data,
        fieldMapping: data.field_mapping,
        thresholds: data.thresholds,
        enabledTypes: data.enabled_types,
      });
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : "加载预设失败",
      });
    }
  },
}));
