"use client";

import { useEffect, useState } from "react";
import { getApiBase } from "../../utils/apiBase";
import Logger from "../../utils/logger";

interface PostgisSectionProps {
  addLayer: (layer: any) => void;
  updateLayerStyle: (layerId: string, style: any) => void;
}

export default function PostgisSection({
  addLayer,
  updateLayerStyle,
}: PostgisSectionProps) {
  const [tables, setTables] = useState<{ schema: string; table: string; geometry_column: string; type: string }[]>([]);
  const [selectedTableIdx, setSelectedTableIdx] = useState<number>(-1);
  const [isLoadingTables, setIsLoadingTables] = useState<boolean>(false);
  const [isAdding, setIsAdding] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTables = async () => {
    setIsLoadingTables(true);
    setError(null);
    try {
      const response = await fetch(`${getApiBase()}/postgis/tables`);
      if (!response.ok) {
        throw new Error("加载数据库表失败");
      }
      const data = await response.json();
      setTables(data.tables || []);
      if (data.tables && data.tables.length > 0) {
        setSelectedTableIdx(0);
      } else {
        setSelectedTableIdx(-1);
      }
    } catch (err: any) {
      Logger.error("Failed to fetch postgis tables:", err);
      setError(err.message || "无法连接数据库");
    } finally {
      setIsLoadingTables(false);
    }
  };

  useEffect(() => {
    fetchTables();
  }, []);

  const handleAddLayer = async () => {
    if (selectedTableIdx < 0 || selectedTableIdx >= tables.length) return;
    const tableInfo = tables[selectedTableIdx];
    
    setIsAdding(true);
    setError(null);
    
    try {
      const API_BASE_URL = getApiBase();
      const response = await fetch(
        `${API_BASE_URL}/postgis/layer/${tableInfo.schema}/${tableInfo.table}?geom_column=${tableInfo.geometry_column}`
      );
      
      if (!response.ok) {
        throw new Error(`加载图层失败 (${response.statusText})`);
      }
      
      const { url, id } = await response.json();
      
      // Create new layer definition
      const newLayer = {
        id: id,
        name: `${tableInfo.schema}.${tableInfo.table}`,
        data_type: "postgis",
        data_link: url,
        visible: true,
        data_source_id: "postgis_direct",
        data_origin: "database",
        data_source: "postgis",
        layer_type: "VECTOR",
      };

      // Add to store
      addLayer(newLayer);

      // Trigger auto style
      try {
        const styleResponse = await fetch(`${API_BASE_URL}/ai-style`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            query: `Auto-style the layer "${newLayer.name}"`,
            geodata_layers: [newLayer],
          }),
        });

        if (styleResponse.ok) {
          const styleResult = await styleResponse.json();
          if (styleResult.success && styleResult.styled_layers.length > 0) {
            const styledLayer = styleResult.styled_layers[0];
            if (styledLayer.style) {
              updateLayerStyle(id, styledLayer.style);
            }
          }
        }
      } catch (styleErr) {
        Logger.warn("Auto-styling for PostGIS layer failed", styleErr);
      }
      
    } catch (err: any) {
      Logger.error("Error adding postgis layer:", err);
      setError(err.message || "加载图层出错");
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <div className="mb-4">
      <h3 className="font-semibold mb-2">连接至 PostGIS</h3>
      <div className="p-4 rounded border border-primary-200 bg-primary-100">
        <div className="flex flex-col gap-2">
          {isLoadingTables ? (
            <p className="text-sm text-neutral-500 text-center py-2">加载中...</p>
          ) : tables.length > 0 ? (
            <>
              <label className="text-sm font-medium text-neutral-700">选择空间数据表</label>
              <select
                className="w-full rounded border border-primary-300 bg-white px-2 py-1.5 text-sm outline-none"
                value={selectedTableIdx}
                onChange={(e) => setSelectedTableIdx(Number(e.target.value))}
                disabled={isAdding}
              >
                {tables.map((tbl, idx) => (
                  <option key={`${tbl.schema}.${tbl.table}`} value={idx}>
                    {tbl.schema}.{tbl.table} ({tbl.geom_column || tbl.geometry_column})
                  </option>
                ))}
              </select>

              <button
                onClick={handleAddLayer}
                disabled={isAdding || selectedTableIdx === -1}
                className="mt-2 w-full rounded bg-primary-600 px-4 py-2 text-sm text-white font-medium hover:bg-primary-700 disabled:opacity-50 transition-colors"
              >
                {isAdding ? "正在加载并处理图层..." : "加至地图"}
              </button>
            </>
          ) : (
            <div className="text-center py-2">
              <p className="text-sm text-neutral-500">未找到任意空间数据表</p>
              <button 
                onClick={fetchTables}
                className="mt-2 text-xs text-primary-600 hover:text-primary-800 underline"
              >
                刷新重试
              </button>
            </div>
          )}

          {error && (
            <div className="mt-2 p-2 bg-danger-100 border border-danger-400 text-danger-700 text-sm rounded">
              {error}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
