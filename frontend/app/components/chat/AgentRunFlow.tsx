"use client";

import React, { useId, useState } from "react";
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  ClipboardList,
  Loader2,
  PlayCircle,
  Wrench,
  XCircle,
} from "lucide-react";
import { ExecutionPlan, ToolUpdate } from "../../stores/chatInterfaceStore";

type AgentRunFlowProps = {
  plan: ExecutionPlan | null;
  toolUpdates: ToolUpdate[];
  isStreaming: boolean;
  onConfirm: () => void;
  onCancel: () => void;
};

type InputRecord = Record<string, unknown>;

function asRecord(value: unknown): InputRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as InputRecord;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function formatValueList(value: unknown): string | null {
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(", ");
  }
  return asString(value);
}

function formatToolInput(input: unknown): string | null {
  const record = asRecord(input);
  if (!record) {
    return null;
  }

  const params: string[] = [];
  const operation = asString(record.operation) || asString(record.operator);
  const query =
    asString(record.query) ||
    asString(record.search_query) ||
    asString(record.location);
  const field = asString(record.field) || formatValueList(record.columns);
  const layer =
    asString(record.target_layer_name) ||
    asString(record.layer_name) ||
    asString(record.layer_id) ||
    formatValueList(record.target_layer_names) ||
    formatValueList(record.layer_names) ||
    formatValueList(record.layer_ids);

  if (operation) params.push(`操作：${operation}`);
  if (query) params.push(`查询：${query}`);
  if (layer) params.push(`图层：${layer}`);
  if (field) params.push(`字段：${field}`);
  if (record.distance !== undefined) params.push(`距离：${record.distance} 米`);
  if (record.buffer_distance !== undefined) {
    params.push(`缓冲距离：${record.buffer_distance} 米`);
  }
  if (record.limit !== undefined) params.push(`限制：${record.limit}`);
  if (record.max_results !== undefined) {
    params.push(`最大数量：${record.max_results}`);
  }

  return params.length ? params.join("；") : null;
}

function formatToolName(name: string): string {
  return name
    .replace(/_/g, " ")
    .replace(/([A-Z])/g, " $1")
    .trim()
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

function statusLabel(status: ToolUpdate["status"]): string {
  if (status === "running") return "运行中";
  if (status === "error") return "失败";
  return "完成";
}

export default function AgentRunFlow({
  plan,
  toolUpdates,
  isStreaming,
  onConfirm,
  onCancel,
}: AgentRunFlowProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const detailsId = useId();

  if (!plan && toolUpdates.length === 0) {
    return null;
  }

  const completed = toolUpdates.filter((tool) => tool.status === "complete").length;
  const failed = toolUpdates.filter((tool) => tool.status === "error").length;
  const running = toolUpdates.filter((tool) => tool.status === "running").length;
  const isPendingPlan = plan?.status === "pending";
  const toggleLabel = isExpanded ? "收起" : "展开";

  return (
    <section
      className={`tool-progress-container agent-run-flow ${
        isExpanded ? "agent-run-flow-expanded" : "agent-run-flow-collapsed"
      }`}
    >
      <div className="tool-progress-header agent-run-flow-header">
        <div className="agent-run-flow-title">
          <ClipboardList size={16} aria-hidden="true" />
          <span className="tool-progress-title">执行流程</span>
        </div>
        <div className="agent-run-flow-controls">
          <div className="agent-run-flow-summary">
            {isStreaming && running > 0 ? "运行中" : "已记录"}
            {toolUpdates.length > 0 && (
              <span>
                {completed} 完成
                {failed > 0 ? `，${failed} 失败` : ""}
              </span>
            )}
          </div>
          {isPendingPlan && (
            <div className="agent-run-actions agent-run-actions-inline">
              <button
                type="button"
                className="agent-run-action agent-run-action-primary"
                onClick={onConfirm}
              >
                <PlayCircle size={16} aria-hidden="true" />
                执行计划
              </button>
              <button
                type="button"
                className="agent-run-action agent-run-action-secondary"
                onClick={onCancel}
              >
                <XCircle size={16} aria-hidden="true" />
                取消
              </button>
            </div>
          )}
          <button
            type="button"
            className="agent-run-expand-toggle"
            aria-expanded={isExpanded}
            aria-controls={detailsId}
            aria-label={`${toggleLabel}执行流程`}
            onClick={() => setIsExpanded((expanded) => !expanded)}
          >
            {isExpanded ? (
              <ChevronDown size={16} aria-hidden="true" />
            ) : (
              <ChevronRight size={16} aria-hidden="true" />
            )}
            <span>{toggleLabel}</span>
          </button>
        </div>
      </div>

      {isExpanded && (
        <div id={detailsId} className="agent-run-flow-details">
          {plan && (
            <div className="agent-run-plan">
              <div className="agent-run-plan-heading">
                <div>
                  <div className="agent-run-section-label">计划</div>
                  <div className="agent-run-plan-title">{plan.title}</div>
                </div>
                <span
                  className={`agent-run-plan-status agent-run-plan-${plan.status}`}
                >
                  {plan.status === "pending"
                    ? "待确认"
                    : plan.status === "confirmed"
                      ? "已确认"
                      : "已取消"}
                </span>
              </div>

              <div className="agent-run-plan-steps">
                {plan.steps.map((step, index) => (
                  <div className="agent-run-step" key={`${step.tool}-${index}`}>
                    <span className="agent-run-step-index">{index + 1}</span>
                    <div className="agent-run-step-body">
                      <div className="agent-run-step-action">{step.action}</div>
                      <div className="agent-run-step-meta">
                        <Wrench size={12} aria-hidden="true" />
                        <span>{step.tool}</span>
                      </div>
                      {step.reason && (
                        <div className="agent-run-step-reason">{step.reason}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {toolUpdates.length > 0 && (
            <div className="agent-run-tools">
              <div className="agent-run-section-label">执行记录</div>
              <div className="tool-progress-list">
                {toolUpdates.map((tool, index) => {
                  const formattedParams = formatToolInput(tool.input);
                  const preview =
                    tool.output_preview &&
                    tool.output_preview !== "Completed (state updated)"
                      ? tool.output_preview
                      : null;

                  return (
                    <div
                      key={tool.id || tool.tool_call_id || `${tool.name}-${index}`}
                      className={`tool-progress-item tool-progress-${tool.status}`}
                    >
                      <div className="tool-progress-icon">
                        {tool.status === "running" && (
                          <Loader2 className="tool-spinner" aria-hidden="true" />
                        )}
                        {tool.status === "complete" && (
                          <CheckCircle2 className="tool-check" aria-hidden="true" />
                        )}
                        {tool.status === "error" && (
                          <AlertCircle className="tool-error" aria-hidden="true" />
                        )}
                      </div>
                      <div className="tool-progress-content">
                        <div className="agent-run-tool-title">
                          <span className="tool-progress-name">
                            {formatToolName(tool.name)}
                          </span>
                          <span className="agent-run-tool-status">
                            {statusLabel(tool.status)}
                          </span>
                        </div>
                        {formattedParams && (
                          <span className="tool-progress-params">
                            {formattedParams}
                          </span>
                        )}
                        {preview && (
                          <span className="agent-run-output-preview">{preview}</span>
                        )}
                        {tool.error && (
                          <span className="tool-progress-error">{tool.error}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}