"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLayerStore } from "../../stores/layerStore";
import {
  DEFAULT_TYPE_COLORS,
  DEFAULT_TYPE_LABELS,
  InefficientType,
  TypeThresholds,
  useInefficientSpaceStore,
} from "../../stores/inefficientSpaceStore";
import { getApiBase, getUploadUrl } from "../../utils/apiBase";
import { GeoDataObject, LayerStyle } from "../../models/geodatamodel";

const TYPE_KEYS: InefficientType[] = [
  "idle_vacant",
  "industrial",
  "commercial",
  "residential",
];

const THRESHOLD_FIELDS: Array<{
  key: keyof TypeThresholds;
  label: string;
  step: number;
}> = [
  { key: "max_far", label: "容积率上限", step: 0.05 },
  { key: "max_building_density", label: "建筑密度上限", step: 0.05 },
  { key: "min_idle_years", label: "闲置年限下限", step: 0.5 },
  { key: "min_tax_output", label: "税收产出下限", step: 1 },
  { key: "near_zero_far", label: "近零容积率", step: 0.01 },
  { key: "near_zero_density", label: "近零建筑密度", step: 0.01 },
];

type LayerRole = "parcel" | "poi" | "enterprise";

type PostgisTable = {
  schema: string;
  table: string;
  geometry_column: string;
  geom_column?: string;
  type?: string;
};

function buildThematicStyle(colors: Record<string, string>): LayerStyle {
  return {
    stroke_color: "#2c3e50",
    stroke_weight: 1.5,
    stroke_opacity: 1,
    fill_opacity: 0.65,
    style_conditions: {
      inefficient_type: {
        color_map: colors,
      },
    },
  };
}

export default function InefficientSpacePanel() {
  const layers = useLayerStore((s) => s.layers);
  const addLayer = useLayerStore((s) => s.addLayer);
  const updateLayerStyle = useLayerStore((s) => s.updateLayerStyle);

  const parcelLayerId = useInefficientSpaceStore((s) => s.parcelLayerId);
  const poiLayerId = useInefficientSpaceStore((s) => s.poiLayerId);
  const enterpriseLayerId = useInefficientSpaceStore((s) => s.enterpriseLayerId);
  const fieldMapping = useInefficientSpaceStore((s) => s.fieldMapping);
  const thresholds = useInefficientSpaceStore((s) => s.thresholds);
  const enabledTypes = useInefficientSpaceStore((s) => s.enabledTypes);
  const includeNonMatch = useInefficientSpaceStore((s) => s.includeNonMatch);
  const resultName = useInefficientSpaceStore((s) => s.resultName);
  const presets = useInefficientSpaceStore((s) => s.presets);
  const loading = useInefficientSpaceStore((s) => s.loading);
  const error = useInefficientSpaceStore((s) => s.error);

  const setParcelLayerId = useInefficientSpaceStore((s) => s.setParcelLayerId);
  const setPoiLayerId = useInefficientSpaceStore((s) => s.setPoiLayerId);
  const setEnterpriseLayerId = useInefficientSpaceStore(
    (s) => s.setEnterpriseLayerId,
  );
  const setFieldMapping = useInefficientSpaceStore((s) => s.setFieldMapping);
  const setThreshold = useInefficientSpaceStore((s) => s.setThreshold);
  const toggleEnabledType = useInefficientSpaceStore((s) => s.toggleEnabledType);
  const setIncludeNonMatch = useInefficientSpaceStore((s) => s.setIncludeNonMatch);
  const setResultName = useInefficientSpaceStore((s) => s.setResultName);
  const setSummary = useInefficientSpaceStore((s) => s.setSummary);
  const setLastResultLayerId = useInefficientSpaceStore(
    (s) => s.setLastResultLayerId,
  );
  const setLoading = useInefficientSpaceStore((s) => s.setLoading);
  const setError = useInefficientSpaceStore((s) => s.setError);
  const loadPresets = useInefficientSpaceStore((s) => s.loadPresets);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [activeThresholdType, setActiveThresholdType] =
    useState<InefficientType>("industrial");
  const [dbTables, setDbTables] = useState<PostgisTable[]>([]);
  const [dbTableIdx, setDbTableIdx] = useState(-1);
  const [dbRole, setDbRole] = useState<LayerRole>("parcel");
  const [dbLoadingTables, setDbLoadingTables] = useState(false);
  const [dbLoadingLayer, setDbLoadingLayer] = useState(false);
  const [dbError, setDbError] = useState<string | null>(null);

  useEffect(() => {
    void loadPresets();
  }, [loadPresets]);

  const assignLayerToRole = useCallback(
    (role: LayerRole, layerId: string) => {
      if (role === "parcel") setParcelLayerId(layerId);
      else if (role === "poi") setPoiLayerId(layerId);
      else setEnterpriseLayerId(layerId);
    },
    [setParcelLayerId, setPoiLayerId, setEnterpriseLayerId],
  );

  const fetchDbTables = useCallback(async () => {
    setDbLoadingTables(true);
    setDbError(null);
    try {
      const response = await fetch(`${getApiBase()}/postgis/tables`, {
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error("加载数据库表失败，请检查 GEODATA_DATABASE_URL 配置");
      }
      const data = await response.json();
      const tables = (data.tables || []) as PostgisTable[];
      setDbTables(tables);
      setDbTableIdx(tables.length > 0 ? 0 : -1);
    } catch (err) {
      setDbTables([]);
      setDbTableIdx(-1);
      setDbError(err instanceof Error ? err.message : "无法连接数据库");
    } finally {
      setDbLoadingTables(false);
    }
  }, []);

  useEffect(() => {
    void fetchDbTables();
  }, [fetchDbTables]);

  const typeLabels = presets?.type_labels || DEFAULT_TYPE_LABELS;
  const typeColors = presets?.type_colors || DEFAULT_TYPE_COLORS;

  const findLayerLink = (id: string | null): string | null => {
    if (!id) return null;
    return layers.find((layer) => layer.id === id)?.data_link || null;
  };

  const handleLoadFromDatabase = async () => {
    if (dbTableIdx < 0 || dbTableIdx >= dbTables.length) {
      setDbError("请先选择数据库表");
      return;
    }
    const tableInfo = dbTables[dbTableIdx];
    const geomColumn =
      tableInfo.geometry_column || tableInfo.geom_column || "geom";

    setDbLoadingLayer(true);
    setDbError(null);
    setError(null);
    try {
      const apiBase = getApiBase();
      const response = await fetch(
        `${apiBase}/postgis/layer/${tableInfo.schema}/${tableInfo.table}?geom_column=${encodeURIComponent(geomColumn)}`,
        { credentials: "include" },
      );
      if (!response.ok) {
        throw new Error(`从数据库加载失败 (${response.status})`);
      }
      const { url, id } = await response.json();
      const layer: GeoDataObject = {
        id,
        name: `${tableInfo.schema}.${tableInfo.table}`,
        title: `${tableInfo.schema}.${tableInfo.table}`,
        data_type: "postgis",
        data_link: url,
        visible: true,
        data_source_id: "postgis_direct",
        data_origin: "database",
        data_source: "postgis",
        layer_type: "VECTOR",
      };
      addLayer(layer);
      assignLayerToRole(dbRole, layer.id);
    } catch (err) {
      const message = err instanceof Error ? err.message : "从数据库加载失败";
      setDbError(message);
      setError(message);
    } finally {
      setDbLoadingLayer(false);
    }
  };

  const handleUpload = async (file: File) => {
    setUploadBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await fetch(getUploadUrl(), {
        method: "POST",
        body: form,
        credentials: "include",
      });
      if (!resp.ok) {
        throw new Error(`上传失败 (${resp.status})`);
      }
      const data = await resp.json();
      const layer: GeoDataObject = {
        id: data.id || crypto.randomUUID(),
        data_source_id: "manual",
        data_type: "uploaded",
        data_origin: "uploaded",
        data_source: "user",
        data_link: data.url,
        name: file.name,
        title: file.name,
        visible: true,
        layer_type: "UPLOADED",
      };
      addLayer(layer);
      setParcelLayerId(layer.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploadBusy(false);
    }
  };

  const handleAnalyze = async () => {
    const parcelLink = findLayerLink(parcelLayerId);
    if (!parcelLink) {
      setError("请先从数据库加载或选择地块图层");
      return;
    }
    if (enabledTypes.length === 0) {
      setError("请至少启用一种低效类型");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${getApiBase()}/inefficient-space/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          parcel_data_link: parcelLink,
          poi_data_link: findLayerLink(poiLayerId),
          enterprise_data_link: findLayerLink(enterpriseLayerId),
          field_mapping: fieldMapping,
          thresholds,
          enabled_types: enabledTypes,
          include_non_match: includeNonMatch,
          result_name: resultName || "低效空间判别结果",
        }),
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail?.detail || `判别失败 (${resp.status})`);
      }
      const body = await resp.json();
      const resultLayer = body.layer as GeoDataObject;
      const style = buildThematicStyle(typeColors);
      addLayer({ ...resultLayer, style, visible: true });
      updateLayerStyle(resultLayer.id, style);
      setSummary(body.summary);
      setLastResultLayerId(resultLayer.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "判别失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="w-full h-full overflow-auto bg-primary-50 p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-primary-900">城市低效空间判别</h1>
        <p className="text-sm text-primary-600 mt-1">
          优先从 PostGIS 数据库选择空间表，也可选用已加载图层或上传文件；配置指标后识别工业/商业/居住低效与闲置空地。
        </p>
      </div>

      <section className="rounded border border-primary-200 bg-white p-3 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-primary-800">
            从数据库加载（PostGIS）
          </h2>
          <button
            type="button"
            className="text-xs text-primary-700 underline disabled:opacity-50"
            disabled={dbLoadingTables}
            onClick={() => void fetchDbTables()}
          >
            {dbLoadingTables ? "刷新中..." : "刷新表列表"}
          </button>
        </div>
        {dbLoadingTables ? (
          <p className="text-sm text-primary-500">正在连接数据库...</p>
        ) : dbTables.length > 0 ? (
          <>
            <label className="block text-sm">
              <span className="text-primary-700">空间数据表</span>
              <select
                className="mt-1 w-full rounded border border-primary-300 px-2 py-1.5 bg-white"
                value={dbTableIdx}
                onChange={(e) => setDbTableIdx(Number(e.target.value))}
                disabled={dbLoadingLayer}
              >
                {dbTables.map((tbl, idx) => (
                  <option key={`${tbl.schema}.${tbl.table}`} value={idx}>
                    {tbl.schema}.{tbl.table} (
                    {tbl.geom_column || tbl.geometry_column})
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="text-primary-700">加载为</span>
              <select
                className="mt-1 w-full rounded border border-primary-300 px-2 py-1.5 bg-white"
                value={dbRole}
                onChange={(e) => setDbRole(e.target.value as LayerRole)}
                disabled={dbLoadingLayer}
              >
                <option value="parcel">地块图层</option>
                <option value="poi">POI 图层</option>
                <option value="enterprise">企业工商图层</option>
              </select>
            </label>
            <button
              type="button"
              className="w-full rounded bg-primary-700 text-white px-3 py-2 text-sm hover:bg-primary-800 disabled:opacity-60"
              disabled={dbLoadingLayer || dbTableIdx < 0}
              onClick={() => void handleLoadFromDatabase()}
            >
              {dbLoadingLayer ? "正在从数据库加载..." : "加载并选用"}
            </button>
          </>
        ) : (
          <div className="rounded border border-dashed border-primary-300 bg-primary-50 px-3 py-2 text-sm text-primary-600">
            未检测到可用空间表。请确认后端已配置 `GEODATA_DATABASE_URL`，或改用下方图层选择/文件上传。
          </div>
        )}
        {dbError && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5">
            {dbError}
          </div>
        )}
      </section>

      <section className="rounded border border-primary-200 bg-white p-3 space-y-3">
        <h2 className="text-sm font-semibold text-primary-800">输入图层</h2>
        <p className="text-xs text-primary-500">
          可选用已从数据库加载的图层，或上传本地矢量文件。
        </p>
        <label className="block text-sm">
          <span className="text-primary-700">地块图层（必选）</span>
          <select
            className="mt-1 w-full rounded border border-primary-300 px-2 py-1.5 bg-white"
            value={parcelLayerId || ""}
            onChange={(e) => setParcelLayerId(e.target.value || null)}
          >
            <option value="">请选择图层</option>
            {layers.map((layer) => (
              <option key={layer.id} value={layer.id}>
                {layer.name}
                {layer.data_source === "postgis" ? " [数据库]" : ""}
              </option>
            ))}
          </select>
        </label>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".geojson,.json,.zip,.gpkg"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleUpload(file);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            className="rounded border border-primary-400 text-primary-800 px-3 py-1.5 text-sm hover:bg-primary-100 disabled:opacity-60"
            disabled={uploadBusy}
            onClick={() => fileInputRef.current?.click()}
          >
            {uploadBusy ? "上传中..." : "上传地块矢量（备选）"}
          </button>
        </div>
        <label className="block text-sm">
          <span className="text-primary-700">POI 图层（可选）</span>
          <select
            className="mt-1 w-full rounded border border-primary-300 px-2 py-1.5 bg-white"
            value={poiLayerId || ""}
            onChange={(e) => setPoiLayerId(e.target.value || null)}
          >
            <option value="">不使用</option>
            {layers.map((layer) => (
              <option key={layer.id} value={layer.id}>
                {layer.name}
                {layer.data_source === "postgis" ? " [数据库]" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          <span className="text-primary-700">企业工商图层（可选）</span>
          <select
            className="mt-1 w-full rounded border border-primary-300 px-2 py-1.5 bg-white"
            value={enterpriseLayerId || ""}
            onChange={(e) => setEnterpriseLayerId(e.target.value || null)}
          >
            <option value="">不使用</option>
            {layers.map((layer) => (
              <option key={layer.id} value={layer.id}>
                {layer.name}
                {layer.data_source === "postgis" ? " [数据库]" : ""}
              </option>
            ))}
          </select>
        </label>
      </section>

      <section className="rounded border border-primary-200 bg-white p-3 space-y-2">
        <h2 className="text-sm font-semibold text-primary-800">字段映射</h2>
        {(
          [
            ["far", "容积率"],
            ["building_density", "建筑密度"],
            ["idle_years", "闲置年限"],
            ["tax_output", "税收产出"],
            ["land_use", "用地性质"],
            ["enterprise_tax_field", "企业税收字段"],
          ] as Array<[keyof typeof fieldMapping, string]>
        ).map(([key, label]) => (
          <label key={key} className="block text-sm">
            <span className="text-primary-700">{label}</span>
            <input
              className="mt-1 w-full rounded border border-primary-300 px-2 py-1.5"
              value={fieldMapping[key]}
              onChange={(e) => setFieldMapping({ [key]: e.target.value })}
            />
          </label>
        ))}
      </section>

      <section className="rounded border border-primary-200 bg-white p-3 space-y-3">
        <h2 className="text-sm font-semibold text-primary-800">启用类型</h2>
        <div className="grid grid-cols-2 gap-2">
          {TYPE_KEYS.map((type) => (
            <label
              key={type}
              className="flex items-center gap-2 text-sm rounded border border-primary-100 px-2 py-1.5"
            >
              <input
                type="checkbox"
                checked={enabledTypes.includes(type)}
                onChange={() => toggleEnabledType(type)}
              />
              <span
                className="inline-block w-3 h-3 rounded-sm"
                style={{ backgroundColor: typeColors[type] }}
              />
              {typeLabels[type] || type}
            </label>
          ))}
        </div>
      </section>

      <section className="rounded border border-primary-200 bg-white p-3 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-primary-800">阈值配置</h2>
          <select
            className="rounded border border-primary-300 px-2 py-1 text-sm"
            value={activeThresholdType}
            onChange={(e) =>
              setActiveThresholdType(e.target.value as InefficientType)
            }
          >
            {TYPE_KEYS.map((type) => (
              <option key={type} value={type}>
                {typeLabels[type] || type}
              </option>
            ))}
          </select>
        </div>
        {THRESHOLD_FIELDS.map((field) => (
          <label key={field.key} className="block text-sm">
            <span className="text-primary-700">{field.label}</span>
            <input
              type="number"
              step={field.step}
              className="mt-1 w-full rounded border border-primary-300 px-2 py-1.5"
              value={thresholds[activeThresholdType][field.key]}
              onChange={(e) =>
                setThreshold(
                  activeThresholdType,
                  field.key,
                  Number(e.target.value),
                )
              }
            />
          </label>
        ))}
      </section>

      <section className="rounded border border-primary-200 bg-white p-3 space-y-3">
        <h2 className="text-sm font-semibold text-primary-800">运行选项</h2>
        <label className="block text-sm">
          <span className="text-primary-700">结果图层名称</span>
          <input
            className="mt-1 w-full rounded border border-primary-300 px-2 py-1.5"
            value={resultName}
            onChange={(e) => setResultName(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={includeNonMatch}
            onChange={(e) => setIncludeNonMatch(e.target.checked)}
          />
          结果中保留非低效要素
        </label>
        <button
          type="button"
          className="w-full rounded bg-secondary-700 text-white px-3 py-2 text-sm font-medium hover:bg-secondary-800 disabled:opacity-60"
          disabled={loading}
          onClick={() => void handleAnalyze()}
        >
          {loading ? "正在判别..." : "开始判别"}
        </button>
        {error && (
          <div className="text-sm text-red-600 bg-red-50 border border-red-200 rounded px-2 py-1.5">
            {error}
          </div>
        )}
      </section>
    </div>
  );
}
