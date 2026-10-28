"use client";

import {
  DEFAULT_TYPE_COLORS,
  DEFAULT_TYPE_LABELS,
  useInefficientSpaceStore,
} from "../../stores/inefficientSpaceStore";

function formatArea(sqm: number): string {
  if (!Number.isFinite(sqm) || sqm <= 0) return "0";
  if (sqm >= 1_000_000) return `${(sqm / 1_000_000).toFixed(2)} km²`;
  if (sqm >= 10_000) return `${(sqm / 10_000).toFixed(2)} 公顷`;
  return `${sqm.toFixed(0)} m²`;
}

export default function ResultSummary() {
  const summary = useInefficientSpaceStore((s) => s.summary);
  const presets = useInefficientSpaceStore((s) => s.presets);

  if (!summary) {
    return (
      <div className="rounded border border-primary-200 bg-white p-3 text-sm text-primary-600">
        完成判别后，这里会显示各类型命中数量与面积汇总。
      </div>
    );
  }

  const labels = presets?.type_labels || DEFAULT_TYPE_LABELS;
  const colors = presets?.type_colors || DEFAULT_TYPE_COLORS;
  const entries = Object.entries(summary.by_type || {}).filter(
    ([, value]) => (value?.count || 0) > 0,
  );

  return (
    <div className="space-y-3">
      <div className="rounded border border-primary-200 bg-white p-3">
        <div className="text-sm font-semibold text-primary-800 mb-2">结果摘要</div>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div className="rounded bg-primary-50 px-2 py-1">
            输入要素：{summary.total}
          </div>
          <div className="rounded bg-primary-50 px-2 py-1">
            命中低效：{summary.matched}
          </div>
          <div className="rounded bg-primary-50 px-2 py-1 col-span-2">
            命中面积：{formatArea(summary.area_stats?.matched_area_sqm || 0)}
          </div>
        </div>
      </div>

      <div className="rounded border border-primary-200 bg-white p-3">
        <div className="text-sm font-semibold text-primary-800 mb-2">分类明细</div>
        {entries.length === 0 ? (
          <div className="text-sm text-primary-500">暂无命中要素</div>
        ) : (
          <ul className="space-y-2">
            {entries.map(([type, value]) => (
              <li
                key={type}
                className="flex items-center justify-between text-sm border-b border-primary-100 pb-1 last:border-0"
              >
                <span className="flex items-center gap-2">
                  <span
                    className="inline-block w-3 h-3 rounded-sm"
                    style={{ backgroundColor: colors[type] || "#999" }}
                  />
                  {labels[type] || type}
                </span>
                <span className="text-primary-700">
                  {value.count} 个 / {formatArea(value.area_sqm)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
