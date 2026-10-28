"use client";

import { useState, useRef, useEffect } from "react";
import { useGeoAgent } from "../../hooks/useGeoAgent";
import { useLayerStore } from "../../stores/layerStore";
import {
  useChatInterfaceStore,
  type ExecutionPlan,
} from "../../stores/chatInterfaceStore";
import { useSettingsStore } from "../../stores/settingsStore";
import { GeoDataObject } from "../../models/geodatamodel";
import { getApiBase } from "../../utils/apiBase";
import ChatMessages from "./ChatMessages";
import SearchResults from "./SearchResults";
import ChatInput from "./ChatInput";
import AgentRunFlow from "./AgentRunFlow";
import MarkdownMessage from "./MarkdownMessage";

function isExecutionPlanPreviewMessage(message: {
  type?: string;
  content?: unknown;
}) {
  if (message.type !== "ai" || typeof message.content !== "string") {
    return false;
  }

  const content = message.content;
  const executionPlanText = "\u6267\u884c\u8ba1\u5212";
  const previewText = "\u9884\u89c8";
  const confirmText = "\u786e\u8ba4";
  const startText = "\u5f00\u59cb\u6267\u884c";

  return (
    content.includes(executionPlanText + previewText) ||
    (content.includes(executionPlanText) &&
      content.includes(confirmText) &&
      content.includes(startText))
  );
}

type AgentInterfaceProps = {
  title?: string;
  placeholder?: string;
};

export default function AgentInterface({
  title = "地图助手",
  placeholder = "询问地图、搜索数据，或请求空间分析...",
}: AgentInterfaceProps = {}) {
  const API_BASE_URL = getApiBase();
  const [expandedToolMessage, setExpandedToolMessage] = useState<
    Record<number, boolean>
  >({});
  const [displayPlan, setDisplayPlan] = useState<ExecutionPlan | null>(null);

  const agentActivityRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [scrollLocked, setScrollLocked] = useState(false);

  const { queryGeoAgentStream, cancelRequest } =
    useGeoAgent(API_BASE_URL);

  const input = useChatInterfaceStore((s) => s.input);
  const setInput = useChatInterfaceStore((s) => s.setInput);
  const conversation = useChatInterfaceStore((s) => s.messages);
  const geoDataList = useChatInterfaceStore((s) => s.geoDataList);
  const showGeoDataResults = useChatInterfaceStore((s) => s.showGeoDataResults);
  const loading = useChatInterfaceStore((s) => s.loading);
  const error = useChatInterfaceStore((s) => s.error);
  const toolUpdates = useChatInterfaceStore((s) => s.toolUpdates);
  const streamingMessage = useChatInterfaceStore((s) => s.streamingMessage);
  const isStreaming = useChatInterfaceStore((s) => s.isStreaming);
  const pendingPlan = useChatInterfaceStore((s) => s.pendingPlan);
  const setPendingPlan = useChatInterfaceStore((s) => s.setPendingPlan);

  const planMode = useSettingsStore((s) => s.model_settings.plan_mode);
  const setPlanMode = useSettingsStore((s) => s.setPlanMode);

  const handleConfirmPlan = async () => {
    if (!pendingPlan) return;
    const confirmedPlan = { ...pendingPlan, status: "confirmed" as const };
    setPendingPlan(confirmedPlan);
    setDisplayPlan(confirmedPlan);
    useChatInterfaceStore.getState().setInput("\u786e\u8ba4");
    await queryGeoAgentStream("chat", {
      query: "\u786e\u8ba4",
      executionPlan: confirmedPlan,
    });
  };

  const handleCancelPlan = async () => {
    if (!pendingPlan) return;
    const cancelledPlan = { ...pendingPlan, status: "cancelled" as const };
    setPendingPlan(cancelledPlan);
    setDisplayPlan(cancelledPlan);
    useChatInterfaceStore.getState().setInput("\u53d6\u6d88");
    await queryGeoAgentStream("chat", {
      query: "\u53d6\u6d88",
      executionPlan: cancelledPlan,
    });
  };
  const showToolMessages = false;
  const runFlowPlan = pendingPlan ?? displayPlan;
  const showRunFlow = Boolean(runFlowPlan || toolUpdates.length > 0);
  const visibleConversation = showRunFlow
    ? conversation.filter((message) => !isExecutionPlanPreviewMessage(message))
    : conversation;

  useEffect(() => {
    if (isStreaming && showRunFlow && agentActivityRef.current) {
      setScrollLocked(true);
      agentActivityRef.current.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    } else if (!isStreaming && scrollLocked) {
      const timer = setTimeout(() => {
        setScrollLocked(false);
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [isStreaming, showRunFlow, scrollLocked]);

  useEffect(() => {
    if (pendingPlan) {
      setDisplayPlan(pendingPlan);
    }
  }, [pendingPlan]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    if (!pendingPlan) {
      setDisplayPlan(null);
    }

    await queryGeoAgentStream("chat");
  };

  const handleCancel = async (e: React.FormEvent) => {
    e.preventDefault();
    await cancelRequest();
  };

  const handleLayerSelect = (layer: GeoDataObject) => {
    useLayerStore.getState().addLayer(layer);
  };

  const handleLayerSelectAll = (layers: GeoDataObject[]) => {
    const layerStore = useLayerStore.getState();
    layers.forEach((layer) => layerStore.addLayer(layer));
  };

  const handleToggleToolMessage = (idx: number) => {
    setExpandedToolMessage((prev) => ({
      ...prev,
      [idx]: !prev[idx],
    }));
  };

  return (
    <div className="h-full w-full bg-primary-50 p-4 flex flex-col overflow-hidden relative border-l border-primary-300">
      <h2 className="text-xl font-bold mb-4 text-primary-900 text-center flex-shrink-0">
        {title}
      </h2>

      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto overflow-x-hidden min-h-0"
      >
        <ChatMessages
          conversation={visibleConversation}
          loading={loading}
          showToolMessages={showToolMessages}
          expandedToolMessage={expandedToolMessage}
          onToggleToolMessage={handleToggleToolMessage}
          disableAutoScroll={scrollLocked}
        />

        {showRunFlow && (
          <div ref={agentActivityRef} className="scroll-mt-4">
            <AgentRunFlow
              plan={runFlowPlan}
              toolUpdates={toolUpdates}
              isStreaming={isStreaming}
              onConfirm={handleConfirmPlan}
              onCancel={handleCancelPlan}
            />
          </div>
        )}

        {isStreaming && streamingMessage && (
          <div className="mb-3">
            <div className="flex justify-start">
              <div className="max-w-[80%] px-4 py-2 rounded-lg bg-neutral-50 rounded-tl-none border border-primary-200">
                <MarkdownMessage
                  content={streamingMessage}
                  className="streaming-message"
                />
                <div className="text-xs text-primary-500 mt-1">{"\u667a\u80fd\u4f53"}</div>
              </div>
            </div>
          </div>
        )}

        <SearchResults
          results={showGeoDataResults ? geoDataList : []}
          loading={loading}
          onSelectLayer={handleLayerSelect}
          onSelectAllLayers={handleLayerSelectAll}
        />
      </div>

      <hr className="my-4 flex-shrink-0" />

      <div className="flex-shrink-0">
        {error && (
          <div role="alert" className="mb-3 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 break-words">
            请求未完成：{error}
          </div>
        )}
        <div className="flex justify-between items-center mb-2 px-1">
          <span className="text-xs text-neutral-500">
            {planMode
              ? "\u8ba1\u5212\u6a21\u5f0f\u5df2\u5f00\u542f\uff1a\u6267\u884c\u524d\u9700\u8981\u786e\u8ba4"
              : "\u8ba1\u5212\u6a21\u5f0f\u5df2\u5173\u95ed\uff1a\u81ea\u52a8\u6267\u884c\u4efb\u52a1"}
          </span>
          <label className="flex items-center space-x-2 text-sm text-neutral-600 dark:text-neutral-400 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={planMode || false}
              onChange={(e) => setPlanMode(e.target.checked)}
              className="w-4 h-4 text-primary-600 rounded focus:ring-primary-500 cursor-pointer"
            />
            <span>{"\u8ba1\u5212\u6a21\u5f0f"}</span>
          </label>
        </div>
        <ChatInput
          value={input}
          onChange={setInput}
          onSubmit={handleSubmit}
          onCancel={handleCancel}
          isStreaming={isStreaming}
          placeholder={placeholder}
          disabled={loading}
        />
      </div>
    </div>
  );
}
