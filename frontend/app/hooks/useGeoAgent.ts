// hooks/useGeoAgent.ts
"use client";

import { useRef } from "react";
import {
  ChatMessage,
  GeoDataObject,
  GeoAgentRequest,
  GeoAgentResponse,
} from "../models/geodatamodel";
import { useLayerStore } from "../stores/layerStore";
import {
  useChatInterfaceStore,
  type ExecutionPlan,
} from "../stores/chatInterfaceStore";
import { useSettingsStore } from "../stores/settingsStore";
import Logger from "../utils/logger";
import {
  isOversizedSsePayload,
  sanitizeChatMessages,
  sanitizeToolStartInput,
} from "../utils/chatPayloadSanitize";

type Primitive = string | number | boolean | null | undefined;

type StreamRequestOptions = {
  portal?: string;
  bboxWkt?: string;
  query?: string;
  executionPlan?: ExecutionPlan | null;
};

/**
 * Recursively walk through any value and:
 * - Convert Maps → plain objects
 * - Convert Sets → arrays (deduped by identity)
 * - Deduplicate Arrays
 * - Recurse into plain Objects
 */
function dedupeDeep(value: any): any {
  // Handle Maps
  if (value instanceof Map) {
    const obj: Record<string, any> = {};
    for (const [k, v] of value.entries()) {
      obj[k] = dedupeDeep(v);
    }
    return obj;
  }

  // Handle Sets
  if (value instanceof Set) {
    return Array.from(value).map(dedupeDeep);
  }

  // Handle Arrays
  if (Array.isArray(value)) {
    // First, recurse into each element
    const inner = value.map(dedupeDeep);
    // Then dedupe by identity
    return Array.from(new Set(inner));
  }

  // Handle plain Objects
  if (value !== null && typeof value === "object") {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(value)) {
      out[k] = dedupeDeep(v);
    }
    return out;
  }

  // Primitives pass through
  return value as Primitive;
}

/**
 * Normalize a raw settings snapshot into JSON-serializable plain JS:
 * - Maps → Objects
 * - Sets/Arrays → deduped Arrays
 * - Objects → fully recursed
 */
function normalizeSettings(raw: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [key, val] of Object.entries(raw)) {
    // only transform container types; primitives stay as-is
    if (
      val instanceof Map ||
      val instanceof Set ||
      Array.isArray(val) ||
      (val !== null && typeof val === "object")
    ) {
      out[key] = dedupeDeep(val);
    } else {
      out[key] = val;
    }
  }
  return out;
}

function syncExecutionPlanFromResponse(
  plan: Record<string, unknown> | undefined,
  setPendingPlan: (plan: ExecutionPlan | null) => void,
) {
  if (!plan) return;

  const status = plan.status;
  if (status === "confirmed" || status === "cancelled") {
    setPendingPlan(null);
    return;
  }

  setPendingPlan(plan as unknown as ExecutionPlan);
}

export function useGeoAgent(apiUrl: string) {
  const layerStore = useLayerStore();
  const chatInterfaceStore = useChatInterfaceStore();

  // Persist across re-renders. Plain `let` resets to null when setIsStreaming
  // triggers a re-render, which made cancelRequest early-return and do nothing.
  const abortControllerRef = useRef<AbortController | null>(null);
  const currentStreamIdRef = useRef<string | null>(null);

  const appendHumanMessage = (query: string): ChatMessage[] => {
    const currentState = useChatInterfaceStore.getState();
    const currentMessages = currentState.messages;
    const queryText = query.trim();

    if (!queryText) {
      return currentMessages;
    }

    const lastMessage = currentMessages[currentMessages.length - 1];
    const alreadyPresent =
      lastMessage?.type === "human" && lastMessage.content.trim() === queryText;

    if (alreadyPresent) {
      return currentMessages;
    }

    const messages = sanitizeChatMessages([
      ...currentMessages,
      { content: queryText, type: "human" as const },
    ]);
    currentState.setMessages(messages);
    return messages;
  };

  async function queryGeoAgent(
    endpoint: "chat" | "search" | "geocode" | "geoprocess" | "ai-style",
    layerUrls: string[] = [],
    options?: { portal?: string; bboxWkt?: string },
  ) {
    const params = new URLSearchParams({
      query: chatInterfaceStore.input,
      endpoint,
    }); // unused at the moment? -> Move to Settingsstore
    chatInterfaceStore.setLoading(true);
    chatInterfaceStore.setError("");
    chatInterfaceStore.setShowGeoDataResults(false);

    await useSettingsStore.getState().initializeIfNeeded();
    const rawSettings = useSettingsStore.getState().getSettings();
    //Logger.log(rawSettings);
    const settingsMap = new Map<string, Set<any>>(
      Object.entries(rawSettings)
        // drop methods and any non-arrays
        .filter(([, value]) => Array.isArray(value))
        // for each key, convert its array into a Set
        .map(([key, value]) => [key, new Set(value as any[])] as const),
    );
    //Logger.log(settingsMap)
    const settingsObjOld: Record<string, unknown[]> = Object.fromEntries(
      Array.from(settingsMap.entries()).map(([key, set]) => [
        key,
        Array.from(set), // turn Set → Array
      ]),
    );
    const settingsObj = normalizeSettings(rawSettings);
    Logger.log("SettingsObject:");
    Logger.log(settingsObj);

    try {
      let response = null;
      const fullQuery = chatInterfaceStore.input;
      if (
        endpoint === "geoprocess" ||
        endpoint === "chat" ||
        endpoint === "geocode" ||
        endpoint === "search"
      ) {
        const currentChatState = useChatInterfaceStore.getState();
        const currentLayerState = useLayerStore.getState();
        const queryText = currentChatState.input;
        const requestMessages = appendHumanMessage(queryText);
        const conversationId =
          currentChatState.ensureConversationId?.() ||
          currentChatState.conversationId;
        const payload: GeoAgentRequest = {
          messages: requestMessages,
          query: queryText,
          geodata_last_results: currentChatState.geoDataList,
          geodata_layers: currentLayerState.layers,
          execution_plan: currentChatState.pendingPlan || undefined,
          // global_geodata: layerStore.globalGeodata,
          options: {
            ...settingsObj,
            ...(conversationId ? { conversation_id: conversationId } : {}),
          },
        };
        chatInterfaceStore.setInput("");
        Logger.log("payload");
        Logger.log(payload);
        response = await fetch(`${apiUrl}/${endpoint}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "include",
          body: JSON.stringify(payload),
        });
      } else if (endpoint === "ai-style") {
        // Handle AI styling endpoint
        const currentChatState = useChatInterfaceStore.getState();
        const currentLayerState = useLayerStore.getState();
        const queryText = currentChatState.input;
        const requestMessages = appendHumanMessage(queryText);
        const payload = {
          query: queryText,
          messages: requestMessages,
          geodata_layers: currentLayerState.layers,
          geodata_last_results: currentChatState.geoDataList,
        };
        chatInterfaceStore.setInput("");
        Logger.log("AI Style payload:", payload);
        response = await fetch(`${apiUrl}/${endpoint}`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          credentials: "include",
          body: JSON.stringify(payload),
        });
      } else {
        throw new Error("未知工具");
      }
      if (!response.ok) {
        Logger.log(response);
        throw new Error("网络响应异常");
      }

      if (endpoint === "ai-style") {
        // Handle AI styling response differently
        const data = await response.json();
        Logger.log("AI Style response:", data);
        Logger.log("Current layers before update:", layerStore.layers);

        // Update layers with styling changes
        if (data.updated_layers) {
          Logger.log("Updating layers with:", data.updated_layers);
          layerStore.updateLayersFromBackend(data.updated_layers);
          Logger.log("Current layers after update:", layerStore.layers);
        }

        // Add AI message to conversation
        if (data.response) {
          chatInterfaceStore.setMessages([
            ...chatInterfaceStore.messages,
            { type: "ai", content: data.response },
          ]);
        }

        // Don't update geoDataList for styling operations
        return;
      }

      const data: GeoAgentResponse = await response.json();
      Logger.log(data);
      if (!data.geodata_results) {
        throw new Error("响应缺少 GeoData");
      }
      if (!data.messages) {
        throw new Error("响应缺少消息");
      }

      chatInterfaceStore.setGeoDataList(data.geodata_results);
      chatInterfaceStore.setMessages(sanitizeChatMessages(data.messages));
      syncExecutionPlanFromResponse(
        data.execution_plan,
        chatInterfaceStore.setPendingPlan,
      );
      if (data.geodata_layers)
        layerStore.synchronizeLayersFromBackend(data.geodata_layers);

      // Check if this was a styling operation by looking for style_map_layers in messages
      const isStyleOperation = data.messages.some(
        (msg) =>
          msg.type === "tool" &&
          msg.content?.includes("Successfully applied styling"),
      );

      if (data.geodata_layers) {
        if (isStyleOperation) {
          // For styling operations, use updateLayersFromBackend to preserve existing layers
          Logger.log(
            "Detected styling operation, using updateLayersFromBackend",
          );
          Logger.log("Styling data.geodata_layers:", data.geodata_layers);
          layerStore.updateLayersFromBackend(data.geodata_layers);
        } else {
          // For other operations, use synchronizeLayersFromBackend
          Logger.log("Regular operation, using synchronizeLayersFromBackend");
          layerStore.synchronizeLayersFromBackend(data.geodata_layers);
        }
      }
      //if (data.global_geodata)
      //  layerStore.synchronizeGlobalGeodataFromBackend(data.global_geodata);
    } catch (e: any) {
      chatInterfaceStore.setError(e.message || "Something went wrong");
      chatInterfaceStore.setShowGeoDataResults(false);
    } finally {
      chatInterfaceStore.setLoading(false);
    }
  }

  /**
   * Streaming version of queryGeoAgent using Server-Sent Events (SSE).
   * Provides real-time updates for tool execution and LLM token streaming.
   */
  async function queryGeoAgentStream(
    endpoint: "chat" = "chat",
    options?: StreamRequestOptions,
  ) {
    chatInterfaceStore.setLoading(true);
    chatInterfaceStore.setIsStreaming(true);
    chatInterfaceStore.setError("");
    chatInterfaceStore.clearStreamingMessage();
    chatInterfaceStore.clearToolUpdates();
    chatInterfaceStore.setShowGeoDataResults(false);

    await useSettingsStore.getState().initializeIfNeeded();
    const rawSettings = useSettingsStore.getState().getSettings();
    const settingsObj = normalizeSettings(rawSettings);

    // Two types of IDs:
    // 1. User session_id (persistent): from settings, used for GeoServer layers, conversation history
    // 2. Request stream_id (ephemeral): unique per request, used for cancellation tracking

    // session_id is preserved in settingsObj (set by backend via cookie)
    // It's used to find preloaded GeoServer layers

    // Generate unique stream_id for this specific request (for cancellation)
    const randomSuffix = window.crypto.getRandomValues(new Uint32Array(1))[0].toString(36).substr(2, 9);
    const streamId = `stream_${Date.now()}_${randomSuffix}`;
    currentStreamIdRef.current = streamId;

    // Create new AbortController for this request
    abortControllerRef.current = new AbortController();

    try {
      const currentChatState = useChatInterfaceStore.getState();
      const currentLayerState = useLayerStore.getState();
      const queryText = options?.query ?? currentChatState.input;
      const executionPlan =
        options && "executionPlan" in options
          ? options.executionPlan
          : currentChatState.pendingPlan;
      const requestMessages = appendHumanMessage(queryText);

      const conversationId =
        currentChatState.ensureConversationId?.() ||
        currentChatState.conversationId;

      const payload: GeoAgentRequest = {
        messages: sanitizeChatMessages(requestMessages),
        query: queryText,
        geodata_last_results: currentChatState.geoDataList,
        geodata_layers: currentLayerState.layers,
        execution_plan: executionPlan || undefined,
        options: settingsObj, // Contains session_id for GeoServer layer lookup
      };

      // Add stream_id for request cancellation (separate from user session_id)
      // and conversation_id so backend can persist chat history.
      if (payload.options) {
        (payload.options as any).stream_id = streamId;
        if (conversationId) {
          (payload.options as any).conversation_id = conversationId;
        }
      }

      chatInterfaceStore.setInput("");
      Logger.log("Streaming payload:", payload);

      const response = await fetch(`${apiUrl}/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        credentials: "include",
        body: JSON.stringify(payload),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP 错误，状态码：${response.status}`);
      }

      if (!response.body) {
        throw new Error("响应正文为空");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          Logger.log("Stream complete");
          break;
        }

        // Decode chunk and add to buffer
        buffer += decoder.decode(value, { stream: true });

        // Process complete SSE messages (event: ...\ndata: ...\n\n)
        const messages = buffer.split("\n\n");
        buffer = messages.pop() || ""; // Keep incomplete message in buffer

        for (const message of messages) {
          if (!message.trim()) continue;

          const lines = message.split("\n");
          let eventType = "";
          let eventData = "";

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventType = line.substring(7).trim();
            } else if (line.startsWith("data: ")) {
              eventData = line.substring(6).trim();
            }
          }

          if (!eventType || !eventData) continue;

          if (isOversizedSsePayload(eventData)) {
            Logger.warn(
              `Skipping oversized SSE ${eventType} payload (${eventData.length} chars)`,
            );
            if (eventType === "result") {
              chatInterfaceStore.setError(
                "最终结果过大，未能完整加载到聊天面板。地图图层可能已更新；请开新会话继续，或缩短工具输出后重试。",
              );
            }
            continue;
          }

          try {
            const data = JSON.parse(eventData);

            switch (eventType) {
              case "tool_start":
                Logger.log(`Tool started: ${data.tool}`);
                chatInterfaceStore.addToolUpdate({
                  name: data.tool,
                  tool_call_id: data.tool_call_id,
                  status: "running",
                  // Never store full sandbox `code` blobs in React state.
                  input: sanitizeToolStartInput(data.input),
                });
                break;

              case "tool_end":
                Logger.log(`Tool completed: ${data.tool}`, {
                  output_preview: data.output_preview,
                  is_state_update: data.is_state_update,
                  output_type: data.output_type,
                });
                const toolStatus = data.status === "error" ? "error" : "complete";
                chatInterfaceStore.updateToolStatus(
                  data.tool,
                  toolStatus,
                  data.error_message,
                  undefined,
                  data.output_preview,
                  data.is_state_update,
                  data.output_type,
                  data.tool_call_id,
                );
                break;

              case "llm_token":
                chatInterfaceStore.appendStreamingToken(data.token);
                break;

              case "plan_created":
                Logger.log("Execution plan created:", data);
                chatInterfaceStore.setPendingPlan(data);
                break;

              case "result": {
                Logger.log("Final result received");
                const messages: ChatMessage[] = sanitizeChatMessages(
                  data.messages || [],
                );

                chatInterfaceStore.setGeoDataList(data.geodata_results || []);
                chatInterfaceStore.setMessages(messages);
                syncExecutionPlanFromResponse(
                  data.execution_plan,
                  chatInterfaceStore.setPendingPlan,
                );

                if (data.geodata_layers) {
                  layerStore.synchronizeLayersFromBackend(data.geodata_layers);
                }

                chatInterfaceStore.clearStreamingMessage();
                break;
              }

              case "error":
                Logger.error("Streaming error:", data);
                chatInterfaceStore.setError(
                  data.message || "An error occurred during streaming",
                );
                chatInterfaceStore.setShowGeoDataResults(false);
                break;

              case "done":
                Logger.log("Stream done:", data);
                break;

              case "cancelled":
                Logger.log("Stream cancelled:", data);
                chatInterfaceStore.setError("请求已取消");
                chatInterfaceStore.setShowGeoDataResults(false);
                break;

              default:
                Logger.warn("Unknown event type:", eventType);
            }
          } catch (parseError) {
            Logger.error("Failed to parse event data:", parseError);
            if (eventType === "result") {
              chatInterfaceStore.setError(
                "最终结果解析失败，聊天记录可能不完整。请开新会话重试。",
              );
            }
          }
        }
      }
    } catch (e: any) {
      // Handle abort errors gracefully
      if (e.name === "AbortError") {
        Logger.log("Request was aborted by user");
        chatInterfaceStore.setError("请求已取消");
        chatInterfaceStore.setShowGeoDataResults(false);
      } else {
        Logger.error("Streaming error:", e);
        chatInterfaceStore.setError(e.message || "Something went wrong");
        chatInterfaceStore.setShowGeoDataResults(false);
      }
    } finally {
      Logger.log("Stream finally block - setting loading and isStreaming to false");
      Logger.log("Messages before finally:", chatInterfaceStore.getMessages());
      Logger.log("GeoData before finally:", chatInterfaceStore.getGeoDataList());
      chatInterfaceStore.setLoading(false);
      chatInterfaceStore.setIsStreaming(false);
      // Only clear refs if this stream is still the active one (cancel may have
      // already cleared them or a newer request may have replaced them).
      if (currentStreamIdRef.current === streamId) {
        abortControllerRef.current = null;
        currentStreamIdRef.current = null;
      }
      Logger.log("Messages after finally:", chatInterfaceStore.getMessages());
      Logger.log("GeoData after finally:", chatInterfaceStore.getGeoDataList());
    }
  }

  /**
   * Cancel the currently running streaming request.
   * Notify the backend first (set cancel flag), then abort the client stream.
   */
  async function cancelRequest() {
    const streamId = currentStreamIdRef.current;
    if (!streamId) {
      Logger.warn("No active session to cancel");
      return;
    }

    Logger.log(`Cancelling request for stream: ${streamId}`);

    // Notify backend before aborting so the flag is set while the generator
    // is still running (abort alone does not stop agent tool/LLM work).
    try {
      await fetch(`${apiUrl}/chat/cancel?session_id=${encodeURIComponent(streamId)}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        credentials: "include",
      });
      Logger.log("Backend notified of cancellation");
    } catch (error) {
      Logger.error("Failed to notify backend of cancellation:", error);
    }

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    chatInterfaceStore.setLoading(false);
    chatInterfaceStore.setIsStreaming(false);
    chatInterfaceStore.clearStreamingMessage();
    chatInterfaceStore.clearToolUpdates();
    chatInterfaceStore.setShowGeoDataResults(false);
    chatInterfaceStore.setError("请求已取消");

    abortControllerRef.current = null;
    currentStreamIdRef.current = null;
  }

  return {
    // Only return functions, not state values
    // State should be accessed directly via useChatInterfaceStore selectors
    // for proper reactivity in components
    queryGeoAgent,
    queryGeoAgentStream, // Export streaming function
    cancelRequest, // Export cancel function
    setInput: chatInterfaceStore.setInput,
  };
}
