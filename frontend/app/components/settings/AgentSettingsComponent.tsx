"use client";

import { useState } from "react";
import { useInitializedSettingsStore } from "../../hooks/useInitializedSettingsStore";
import { ChevronDown, ChevronUp, Info } from "lucide-react";

export default function AgentSettingsComponent() {
  const [collapsed, setCollapsed] = useState(true);

  const modelSettings = useInitializedSettingsStore((s) => s.model_settings);
  const setSystemPrompt = useInitializedSettingsStore((s) => s.setSystemPrompt);
  const setEnableDynamicTools = useInitializedSettingsStore(
    (s) => s.setEnableDynamicTools,
  );
  const setToolSelectionStrategy = useInitializedSettingsStore(
    (s) => s.setToolSelectionStrategy,
  );
  const setToolSimilarityThreshold = useInitializedSettingsStore(
    (s) => s.setToolSimilarityThreshold,
  );
  const setMaxToolsPerQuery = useInitializedSettingsStore(
    (s) => s.setMaxToolsPerQuery,
  );
  const setUseSummarization = useInitializedSettingsStore(
    (s) => s.setUseSummarization,
  );
  const setEnableSmartCrs = useInitializedSettingsStore(
    (s) => s.setEnableSmartCrs,
  );

  const toolStrategies = [
    { value: "all", label: "全部工具", description: "提供所有可用工具（默认行为）" },
    { value: "semantic", label: "语义匹配", description: "根据查询相似度选择工具" },
    { value: "conservative", label: "保守模式", description: "平衡选择常用工具" },
    { value: "minimal", label: "最小模式", description: "只提供与查询最相关的工具" },
  ];

  return (
    <div className="border border-primary-300 dark:border-primary-700 rounded bg-primary-50 dark:bg-neutral-900 overflow-hidden">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-3 bg-primary-100 hover:bg-primary-200 dark:bg-primary-900 dark:hover:bg-primary-800 transition-colors"
      >
        <h2 className="text-lg font-semibold text-primary-900 dark:text-primary-100">
          智能体设置
        </h2>
        {collapsed ? (
          <ChevronDown className="w-6 h-6 text-primary-600 dark:text-primary-400" />
        ) : (
          <ChevronUp className="w-6 h-6 text-primary-600 dark:text-primary-400" />
        )}
      </button>

      {!collapsed && (
        <div className="p-4 pt-0 space-y-4">
          {/* System Prompt */}
          <div>
            <label className="block text-sm font-medium text-primary-900 dark:text-primary-300 mb-1">
              系统提示词
            </label>
            <textarea
              value={modelSettings.system_prompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="可选：覆盖默认系统提示词..."
              className="w-full border border-primary-300 dark:border-primary-700 rounded p-2 h-24 bg-primary-50 dark:bg-primary-950 text-primary-900 dark:text-primary-100"
            />
            <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
              自定义智能体的行为与风格
            </p>
          </div>

          {/* Enable Dynamic Tool Selection */}
          <div className="col-span-2">
            <div className="flex items-start gap-2">
              <input
                type="checkbox"
                id="enable-dynamic-tools"
                checked={modelSettings.enable_dynamic_tools ?? false}
                onChange={(e) => setEnableDynamicTools(e.target.checked)}
                className="mt-1 h-4 w-4 rounded border-primary-300 dark:border-primary-700 text-tertiary-600 focus:ring-tertiary-500"
              />
              <div className="flex-1">
                <label
                  htmlFor="enable-dynamic-tools"
                  className="text-sm font-medium text-primary-900 dark:text-primary-300 cursor-pointer"
                >
                  启用动态工具选择
                </label>
                <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
                  基于语义相似度，按查询内容智能选择工具。
                  只提供相关工具以减少令牌用量并提升响应速度。
                  通过嵌入向量支持多语言查询。
                </p>
              </div>
            </div>
          </div>

          {/* Dynamic Tool Settings (shown when enabled) */}
          {modelSettings.enable_dynamic_tools && (
            <>
              {/* Tool Selection Strategy */}
              <div>
                <label className="block text-sm font-medium text-primary-900 dark:text-primary-300 mb-1">
                  工具选择策略
                </label>
                <select
                  value={modelSettings.tool_selection_strategy || "conservative"}
                  onChange={(e) => setToolSelectionStrategy(e.target.value)}
                  className="w-full border border-primary-300 dark:border-primary-700 rounded p-2 bg-primary-50 dark:bg-primary-950 text-primary-900 dark:text-primary-100"
                >
                  {toolStrategies.map((strategy) => (
                    <option key={strategy.value} value={strategy.value} className="bg-primary-50 text-primary-900">
                      {strategy.label}
                    </option>
                  ))}
                </select>
                <div className="mt-2 space-y-1">
                  {toolStrategies.map((strategy) => (
                    <div
                      key={strategy.value}
                      className={`text-xs p-2 rounded ${
                        modelSettings.tool_selection_strategy === strategy.value
                          ? "bg-tertiary-100 dark:bg-tertiary-900 text-tertiary-900 dark:text-tertiary-100"
                          : "bg-primary-100 dark:bg-primary-800 text-primary-700 dark:text-primary-400"
                      }`}
                    >
                      <span className="font-semibold">{strategy.label}:</span> {strategy.description}
                    </div>
                  ))}
                </div>
              </div>

              {/* Tool Similarity Threshold */}
              <div>
                <label className="block text-sm font-medium text-primary-900 dark:text-primary-300 mb-1">
                  工具相似度阈值：{modelSettings.tool_similarity_threshold?.toFixed(2) ?? "0.30"}
                </label>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.05"
                  value={modelSettings.tool_similarity_threshold ?? 0.3}
                  onChange={(e) => setToolSimilarityThreshold(Number(e.target.value))}
                  className="w-full h-2 bg-primary-200 dark:bg-primary-800 rounded-lg appearance-none cursor-pointer accent-tertiary-600"
                />
                <div className="flex justify-between text-xs text-primary-700 dark:text-primary-400 mt-1">
                  <span>0.00（更多工具）</span>
                  <span>1.00（更少工具）</span>
                </div>
                <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
                  工具入选所需的最低相似度。数值越低包含工具越多，数值越高选择越严格。
                </p>
              </div>

              {/* Max Tools Per Query */}
              <div>
                <label className="block text-sm font-medium text-primary-900 dark:text-primary-300 mb-1">
                  每次查询最多工具数
                  <span className="text-xs text-primary-700 dark:text-primary-400 ml-1">
                    (可选)
                  </span>
                </label>
                <input
                  type="number"
                  value={modelSettings.max_tools_per_query ?? ""}
                  onChange={(e) => {
                    const value = e.target.value;
                    if (value === "" || value === null) {
                      setMaxToolsPerQuery(null);
                    } else {
                      const numValue = Number(value);
                      setMaxToolsPerQuery(Math.max(1, numValue));
                    }
                  }}
                  min="1"
                  placeholder="无限制"
                  className="w-full border border-primary-300 dark:border-primary-700 rounded p-2 bg-primary-50 dark:bg-primary-950 text-primary-900 dark:text-primary-100"
                />
                <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
                  提供给智能体的最大工具数量。留空表示不限制。
                </p>
              </div>

              {/* Information Banner */}
              <div className="border border-info-300 dark:border-info-700 rounded bg-info-50 dark:bg-info-900 p-3">
                <div className="flex items-start gap-2">
                  <Info className="w-4 h-4 text-info-600 dark:text-info-400 flex-shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <p className="text-xs text-info-900 dark:text-info-200">
                      <span className="font-semibold">动态工具选择的收益：</span>
                    </p>
                    <ul className="text-xs text-info-800 dark:text-info-300 mt-1 space-y-0.5 list-disc list-inside">
                      <li>只提供相关工具，减少令牌消耗</li>
                      <li>缩小上下文，提高响应速度</li>
                      <li>通过语义相似度支持任意语言</li>
                      <li>嵌入不可用时自动回退到全部工具</li>
                    </ul>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* Enable Conversation Summarization */}
          <div className="col-span-2">
            <div className="flex items-start gap-2">
              <input
                type="checkbox"
                id="enable-summarization"
                checked={modelSettings.use_summarization ?? false}
                onChange={(e) => setUseSummarization(e.target.checked)}
                className="mt-1 h-4 w-4 rounded border-primary-300 dark:border-primary-700 text-tertiary-600 focus:ring-tertiary-500"
              />
              <div className="flex-1">
                <label
                  htmlFor="enable-summarization"
                  className="text-sm font-medium text-primary-900 dark:text-primary-300 cursor-pointer"
                >
                  启用对话摘要
                </label>
                <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
                  在长对话中自动压缩较早消息，降低令牌用量。
                  近期消息会保留，较早消息由 LLM 总结。
                  需要会话 ID 来跟踪对话状态。
                </p>
                <div className="mt-2 border border-info-300 dark:border-info-700 rounded bg-info-50 dark:bg-info-900 p-2">
                  <div className="flex items-start gap-2">
                    <Info className="w-3 h-3 text-info-600 dark:text-info-400 flex-shrink-0 mt-0.5" />
                    <p className="text-xs text-info-900 dark:text-info-200">
                      <span className="font-semibold">收益：</span> 支持更长对话，
                      可降低 50-80% 的令牌成本，并保持上下文质量。对话超过阈值后会自动触发。
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Enable Smart CRS Selection */}
          <div className="col-span-2">
            <div className="flex items-start gap-2">
              <input
                type="checkbox"
                id="enable-smart-crs"
                checked={modelSettings.enable_smart_crs ?? true}
                onChange={(e) => setEnableSmartCrs(e.target.checked)}
                className="mt-1 h-4 w-4 rounded border-primary-300 dark:border-primary-700 text-tertiary-600 focus:ring-tertiary-500"
              />
              <div className="flex-1">
                <label
                  htmlFor="enable-smart-crs"
                  className="text-sm font-medium text-primary-900 dark:text-primary-300 cursor-pointer"
                >
                  启用智能 CRS 选择
                </label>
                <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
                  根据地理范围和操作类型，为地理处理自动选择最佳坐标参考系统（CRS）。
                  可显著提升几何精度：缓冲区误差可从约 20% 降至 &lt;1%，极地区域面积计算误差可从 50%+ 降至 &lt;1%。
                  关闭后将对所有操作使用旧的 EPSG:4326。
                </p>
                <div className="mt-2 border border-info-300 dark:border-info-700 rounded bg-info-50 dark:bg-info-900 p-2">
                  <div className="flex items-start gap-2">
                    <Info className="w-3 h-3 text-info-600 dark:text-info-400 flex-shrink-0 mt-0.5" />
                    <p className="text-xs text-info-900 dark:text-info-200">
                      <span className="font-semibold">投影选择：</span> 使用三层策略：
                      局部区域（&lt;6°）使用 UTM 分区，高纬度（&gt;80°）使用极地投影，
                      区域级操作使用大陆投影。面积/融合使用等面积投影，叠加/裁剪/简化使用保角投影，缓冲区使用最优 CRS。
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
