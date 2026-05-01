"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { useInitializedSettingsStore } from "../../hooks/useInitializedSettingsStore";
import { ChevronDown, ChevronUp, Info } from "lucide-react";

export default function ModelSettingsComponent() {
  const [collapsed, setCollapsed] = useState(true);

  const modelSettings = useInitializedSettingsStore((s) => s.model_settings);
  const setModelProvider = useInitializedSettingsStore(
    (s) => s.setModelProvider,
  );
  const setModelName = useInitializedSettingsStore((s) => s.setModelName);
  const setMaxTokens = useInitializedSettingsStore((s) => s.setMaxTokens);
  const setMessageWindowSize = useInitializedSettingsStore(
    (s) => s.setMessageWindowSize,
  );
  const setEnableParallelTools = useInitializedSettingsStore(
    (s) => s.setEnableParallelTools,
  );
  const setEnablePerformanceMetrics = useInitializedSettingsStore(
    (s) => s.setEnablePerformanceMetrics,
  );

  const availableProviders = useInitializedSettingsStore(
    (s) => s.available_model_providers,
  );
  const availableModelNames = useInitializedSettingsStore(
    (s) => s.available_model_names,
  );
  const modelOptions = useInitializedSettingsStore((s) => s.model_options);
  const setAvailableModelNames = useInitializedSettingsStore(
    (s) => s.setAvailableModelNames,
  );

  // Get currently selected model details
  const selectedModel = useMemo(() => {
    const models = modelOptions[modelSettings.model_provider] || [];
    return models.find((m) => m.name === modelSettings.model_name);
  }, [modelOptions, modelSettings.model_provider, modelSettings.model_name]);

  // Format cost for display
  const formatCost = (cost: number | null | undefined) => {
    if (cost === null || cost === undefined) return "暂无";
    return `$${cost.toFixed(2)}`;
  };

  // Format context window with K/M notation
  const formatContextWindow = (tokens: number | undefined) => {
    if (!tokens) return "未知";
    if (tokens >= 1_000_000) {
      return `${(tokens / 1_000_000).toFixed(1)}M 令牌`;
    }
    if (tokens >= 1_000) {
      return `${(tokens / 1_000).toFixed(0)}K 令牌`;
    }
    return `${tokens} 令牌`;
  };

  // Get quality badge color
  const getQualityColor = (quality: string | undefined) => {
    switch (quality) {
      case "excellent":
        return "text-tertiary-700 dark:text-tertiary-300 bg-tertiary-100 dark:bg-tertiary-900";
      case "good":
        return "text-info-700 dark:text-info-300 bg-info-100 dark:bg-info-900";
      case "basic":
        return "text-warning-700 dark:text-warning-300 bg-warning-100 dark:bg-warning-900";
      case "none":
        return "text-danger-700 dark:text-danger-300 bg-danger-100 dark:bg-danger-900";
      default:
        return "text-primary-700 dark:text-primary-300 bg-primary-100 dark:bg-primary-900";
    }
  };

  const getReasoningColor = (capability: string | undefined) => {
    switch (capability) {
      case "expert":
        return "text-tertiary-700 dark:text-tertiary-300 bg-tertiary-100 dark:bg-tertiary-900";
      case "advanced":
        return "text-info-700 dark:text-info-300 bg-info-100 dark:bg-info-900";
      case "intermediate":
        return "text-warning-700 dark:text-warning-300 bg-warning-100 dark:bg-warning-900";
      case "basic":
        return "text-danger-700 dark:text-danger-300 bg-danger-100 dark:bg-danger-900";
      default:
        return "text-primary-700 dark:text-primary-300 bg-primary-100 dark:bg-primary-900";
    }
  };

  return (
    <div className="border border-primary-300 dark:border-primary-700 rounded bg-primary-50 dark:bg-neutral-900 overflow-hidden">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-3 bg-primary-100 hover:bg-primary-200 dark:bg-primary-900 dark:hover:bg-primary-800 transition-colors"
      >
        <h2 className="text-lg font-semibold text-primary-900 dark:text-primary-100">
          模型设置
        </h2>
        {collapsed ? (
          <ChevronDown className="w-6 h-6 text-primary-600 dark:text-primary-400" />
        ) : (
          <ChevronUp className="w-6 h-6 text-primary-600 dark:text-primary-400" />
        )}
      </button>

      {!collapsed && (
        <div className="p-4 pt-0 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="block text-sm font-medium text-primary-900 dark:text-primary-300 mb-1">
                服务提供商
              </label>
              <select
                value={modelSettings.model_provider}
                onChange={(e) => {
                  const prov = e.target.value;
                  setModelProvider(prov);
                  const models = modelOptions[prov] || [];
                  const names = models.map((m) => m.name);
                  setAvailableModelNames(names);
                  if (models.length) {
                    setModelName(names[0]);
                    setMaxTokens(models[0].max_tokens);
                  }
                }}
                className="w-full border border-primary-300 dark:border-primary-700 rounded p-2 bg-primary-50 dark:bg-primary-950 text-primary-900 dark:text-primary-100"
              >
                {availableProviders.map((prov) => (
                  <option key={prov} value={prov} className="bg-primary-50 text-primary-900">
                    {prov.charAt(0).toUpperCase() + prov.slice(1)}
                  </option>
                ))}
              </select>
            </div>

            <div className="col-span-2">
              <label className="block text-sm font-medium text-primary-900 dark:text-primary-300 mb-1">
                模型
              </label>
              <select
                value={modelSettings.model_name}
                onChange={(e) => {
                  const newModelName = e.target.value;
                  setModelName(newModelName);
                  const models = modelOptions[modelSettings.model_provider] || [];
                  const selectedModelData = models.find((m) => m.name === newModelName);
                  if (selectedModelData) {
                    setMaxTokens(selectedModelData.max_tokens);
                  }
                }}
                className="w-full border border-primary-300 dark:border-primary-700 rounded p-2 bg-primary-50 dark:bg-primary-950 text-primary-900 dark:text-primary-100"
              >
                {availableModelNames.map((name) => (
                  <option key={name} value={name} className="bg-primary-50 text-primary-900">
                    {name}
                  </option>
                ))}
              </select>
            </div>

            <div className="col-span-2">
              <label className="block text-sm font-medium text-primary-900 dark:text-primary-300 mb-1">
                最大输出令牌数
                {selectedModel && (
                  <span className="text-xs text-primary-700 dark:text-primary-400 ml-1">
                    (0 到 {selectedModel.max_tokens.toLocaleString()})
                  </span>
                )}
              </label>
              <input
                type="number"
                value={modelSettings.max_tokens}
                onChange={(e) => {
                  const value = Number(e.target.value);
                  if (selectedModel) {
                    // Clamp between 0 and model's max_tokens
                    const clampedValue = Math.max(0, Math.min(value, selectedModel.max_tokens));
                    setMaxTokens(clampedValue);
                  } else {
                    setMaxTokens(value);
                  }
                }}
                min="0"
                max={selectedModel?.max_tokens || undefined}
                placeholder="最大令牌数"
                className="w-full border border-primary-300 dark:border-primary-700 rounded p-2 bg-primary-50 dark:bg-primary-950 text-primary-900 dark:text-primary-100"
              />
              <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
                每次响应最多生成的令牌数
              </p>
            </div>

            {/* Message Window Size */}
            <div className="col-span-2">
              <label className="block text-sm font-medium text-primary-900 dark:text-primary-300 mb-1">
                消息窗口大小
                <span className="text-xs text-primary-700 dark:text-primary-400 ml-1">
                  (可选)
                </span>
              </label>
              <input
                type="number"
                value={modelSettings.message_window_size ?? ""}
                onChange={(e) => {
                  const value = e.target.value;
                  if (value === "" || value === null) {
                    setMessageWindowSize(null);
                  } else {
                    const numValue = Number(value);
                    setMessageWindowSize(Math.max(0, numValue));
                  }
                }}
                min="0"
                placeholder="20（默认）"
                className="w-full border border-primary-300 dark:border-primary-700 rounded p-2 bg-primary-50 dark:bg-primary-950 text-primary-900 dark:text-primary-100"
              />
              <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
                保留在上下文中的最近消息数量。留空则使用默认值（20）。
                设为 0 可禁用裁剪。数值越高，成本越高。
              </p>
            </div>

            {/* Enable Parallel Tools */}
            <div className="col-span-2">
              <div className="flex items-start gap-2">
                <input
                  type="checkbox"
                  id="enable-parallel-tools"
                  checked={modelSettings.enable_parallel_tools ?? false}
                  onChange={(e) => setEnableParallelTools(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-primary-300 dark:border-primary-700 text-tertiary-600 focus:ring-tertiary-500"
                />
                <div className="flex-1">
                  <label
                    htmlFor="enable-parallel-tools"
                    className="text-sm font-medium text-primary-900 dark:text-primary-300 cursor-pointer"
                  >
                    启用并行工具执行
                    {selectedModel?.supports_parallel_tool_calls && (
                      <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium text-tertiary-700 dark:text-tertiary-300 bg-tertiary-100 dark:bg-tertiary-900">
                        支持
                      </span>
                    )}
                    {!selectedModel?.supports_parallel_tool_calls && (
                      <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium text-danger-700 dark:text-danger-300 bg-danger-100 dark:bg-danger-900">
                        不支持
                      </span>
                    )}
                  </label>
                  <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
                    <span className="font-semibold text-warning-700 dark:text-warning-300">
                      实验功能：
                    </span>{" "}
                    允许并发执行工具，从而加快多工具查询。
                    {!selectedModel?.supports_parallel_tool_calls && 
                      " 当前模型不支持并行工具调用。"
                    }
                    {selectedModel?.supports_parallel_tool_calls && 
                      " 可能导致状态冲突，请留意异常。"
                    }
                  </p>
                </div>
              </div>
            </div>

            {/* Enable Performance Metrics */}
            <div className="col-span-2">
              <div className="flex items-start gap-2">
                <input
                  type="checkbox"
                  id="enable-performance-metrics"
                  checked={modelSettings.enable_performance_metrics ?? false}
                  onChange={(e) => setEnablePerformanceMetrics(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-primary-300 dark:border-primary-700 text-tertiary-600 focus:ring-tertiary-500"
                />
                <div className="flex-1">
                  <label
                    htmlFor="enable-performance-metrics"
                    className="text-sm font-medium text-primary-900 dark:text-primary-300 cursor-pointer"
                  >
                    启用性能指标
                    <span className="ml-2 px-2 py-0.5 rounded text-xs font-medium text-info-700 dark:text-info-300 bg-info-100 dark:bg-info-900">
                      监控
                    </span>
                  </label>
                  <p className="text-xs text-primary-700 dark:text-primary-400 mt-1">
                    跟踪耗时、令牌用量和工具性能。
                    {modelSettings.enable_performance_metrics && (
                      <>
                        {" "}
                        <Link
                          href="/metrics"
                          className="text-tertiary-600 dark:text-tertiary-400 hover:text-tertiary-700 dark:hover:text-tertiary-300 underline"
                        >
                          查看指标面板
                        </Link>
                      </>
                    )}
                    {!modelSettings.enable_performance_metrics && (
                      <>
                        {" "}
                        指标也可通过 <code className="px-1 py-0.5 bg-primary-200 dark:bg-primary-800 rounded text-xs">/metrics</code> 端点查看。
                      </>
                    )}
                    {" "}不会影响响应速度。
                  </p>
                </div>
              </div>
            </div>
          </div>

          {/* Model Information Card */}
          {selectedModel && (
            <div className="border border-secondary-300 dark:border-secondary-700 rounded bg-secondary-50 dark:bg-secondary-900 p-3 space-y-3">
              <div className="flex items-start gap-2">
                <Info className="w-4 h-4 text-secondary-600 dark:text-secondary-400 flex-shrink-0 mt-0.5" />
                <div className="flex-1 space-y-3">
                  {selectedModel.description && (
                    <p className="text-sm text-primary-900 dark:text-primary-300">
                      {selectedModel.description}
                    </p>
                  )}

                  {/* Context Window & Capabilities */}
                  <div className="space-y-2">
                    {selectedModel.context_window && (
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-primary-800 dark:text-primary-400 font-medium">
                          上下文窗口：
                        </span>
                        <span className="text-xs text-primary-900 dark:text-primary-200 font-semibold">
                          {formatContextWindow(selectedModel.context_window)}
                        </span>
                      </div>
                    )}

                    {/* Capability Badges */}
                    <div className="flex flex-wrap gap-2">
                      {selectedModel.reasoning_capability && (
                        <span
                          className={`px-2 py-1 rounded text-xs font-medium ${getReasoningColor(
                            selectedModel.reasoning_capability
                          )}`}
                        >
                          {selectedModel.reasoning_capability.charAt(0).toUpperCase() +
                            selectedModel.reasoning_capability.slice(1)}{" "}
                          推理
                        </span>
                      )}

                      {selectedModel.tool_calling_quality && (
                        <span
                          className={`px-2 py-1 rounded text-xs font-medium ${getQualityColor(
                            selectedModel.tool_calling_quality
                          )}`}
                        >
                          {selectedModel.tool_calling_quality.charAt(0).toUpperCase() +
                            selectedModel.tool_calling_quality.slice(1)}{" "}
                          工具
                        </span>
                      )}

                      {selectedModel.supports_parallel_tool_calls && (
                        <span className="px-2 py-1 rounded text-xs font-medium text-tertiary-700 dark:text-tertiary-300 bg-tertiary-100 dark:bg-tertiary-900">
                          并行工具
                        </span>
                      )}

                      {selectedModel.supports_vision && (
                        <span className="px-2 py-1 rounded text-xs font-medium text-info-700 dark:text-info-300 bg-info-100 dark:bg-info-900">
                          视觉
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Pricing Information */}
                  <div className="grid grid-cols-2 gap-2 text-xs border-t border-secondary-200 dark:border-secondary-800 pt-2">
                    {(selectedModel.input_cost_per_million !== null &&
                      selectedModel.input_cost_per_million !== undefined) && (
                      <div>
                        <span className="text-primary-800 dark:text-primary-400 font-medium">
                          输入：
                        </span>{" "}
                        <span className="text-primary-900 dark:text-primary-200">
                          {formatCost(selectedModel.input_cost_per_million)}/M
                        </span>
                      </div>
                    )}

                    {(selectedModel.output_cost_per_million !== null &&
                      selectedModel.output_cost_per_million !== undefined) && (
                      <div>
                        <span className="text-primary-800 dark:text-primary-400 font-medium">
                          输出：
                        </span>{" "}
                        <span className="text-primary-900 dark:text-primary-200">
                          {formatCost(selectedModel.output_cost_per_million)}/M
                        </span>
                      </div>
                    )}

                    {(selectedModel.cache_cost_per_million !== null &&
                      selectedModel.cache_cost_per_million !== undefined) && (
                      <div className="col-span-2">
                        <span className="text-primary-800 dark:text-primary-400 font-medium">
                          缓存：
                        </span>{" "}
                        <span className="text-primary-900 dark:text-primary-200">
                          {formatCost(selectedModel.cache_cost_per_million)}/M
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

