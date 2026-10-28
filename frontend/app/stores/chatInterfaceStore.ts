// stores/chatInterfaceStore.ts
import { create } from "zustand";
import { ChatMessage, GeoDataObject } from "../models/geodatamodel";

function createConversationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `conversation_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
}

export type PlanStep = {
  action: string;
  tool: string;
  reason?: string;
};

export type ExecutionPlan = {
  title: string;
  steps: PlanStep[];
  summary: string;
  status: "pending" | "confirmed" | "cancelled";
  step_count?: number;
};

export type ToolUpdate = {
  id: string;
  name: string;
  tool_call_id?: string | null;
  status: "running" | "complete" | "error";
  timestamp: number;
  error?: string;
  input?: unknown;
  output?: unknown;
  output_preview?: string;
  is_state_update?: boolean;
  output_type?: string;
};

type ToolUpdateInput = Omit<ToolUpdate, "id" | "timestamp">;

function buildToolUpdateId(
  toolName: string,
  toolCallId: string | null | undefined,
  timestamp: number,
  index: number,
) {
  return toolCallId || `${toolName}-${timestamp}-${index}`;
}

export type ChatInterfaceState = {
  input: string;
  messages: ChatMessage[];
  conversationId: string;
  geoDataList: GeoDataObject[];
  showGeoDataResults: boolean;
  loading: boolean;
  error: string;
  toolUpdates: ToolUpdate[];
  streamingMessage: string;
  isStreaming: boolean;
  pendingPlan: ExecutionPlan | null;

  getInput: () => string;
  getMessages: () => ChatMessage[];
  getConversationId: () => string;
  getGeoDataList: () => GeoDataObject[];
  getShowGeoDataResults: () => boolean;
  getLoading: () => boolean;
  getError: () => string;
  getToolUpdates: () => ToolUpdate[];
  getStreamingMessage: () => string;
  getIsStreaming: () => boolean;
  getPendingPlan: () => ExecutionPlan | null;

  setInput: (input: string) => void;
  addMessage: (message: ChatMessage) => void;
  setMessages: (messages: ChatMessage[]) => void;
  clearMessages: () => void;
  ensureConversationId: () => string;
  startNewConversation: () => string;
  setGeoDataList: (list: GeoDataObject[]) => void;
  setShowGeoDataResults: (flag: boolean) => void;
  addGeoData: (item: GeoDataObject) => void;
  setLoading: (flag: boolean) => void;
  setError: (error: string) => void;
  clearError: () => void;
  addToolUpdate: (tool: ToolUpdateInput) => void;
  updateToolStatus: (
    toolName: string,
    status: ToolUpdate["status"],
    error?: string,
    output?: unknown,
    output_preview?: string,
    is_state_update?: boolean,
    output_type?: string,
    toolCallId?: string | null,
  ) => void;
  appendStreamingToken: (token: string) => void;
  setStreamingMessage: (message: string) => void;
  clearStreamingMessage: () => void;
  clearToolUpdates: () => void;
  setIsStreaming: (flag: boolean) => void;
  setPendingPlan: (plan: ExecutionPlan | null) => void;
};

export const useChatInterfaceStore = create<ChatInterfaceState>((set, get) => ({
  input: "",
  messages: [],
  conversationId: createConversationId(),
  geoDataList: [],
  showGeoDataResults: false,
  loading: false,
  error: "",
  toolUpdates: [],
  streamingMessage: "",
  isStreaming: false,
  pendingPlan: null,

  getInput: () => get().input,
  getMessages: () => get().messages,
  getConversationId: () => get().conversationId,
  getGeoDataList: () => get().geoDataList,
  getShowGeoDataResults: () => get().showGeoDataResults,
  getLoading: () => get().loading,
  getError: () => get().error,
  getToolUpdates: () => get().toolUpdates,
  getStreamingMessage: () => get().streamingMessage,
  getIsStreaming: () => get().isStreaming,
  getPendingPlan: () => get().pendingPlan,

  setInput: (input) => set({ input }),
  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),
  setMessages: (messages) => set({ messages }),
  clearMessages: () => set({ messages: [], conversationId: createConversationId() }),
  ensureConversationId: () => {
    const current = get().conversationId;
    if (current) {
      return current;
    }
    const next = createConversationId();
    set({ conversationId: next });
    return next;
  },
  startNewConversation: () => {
    const next = createConversationId();
    set({
      conversationId: next,
      messages: [],
      geoDataList: [],
      showGeoDataResults: false,
      streamingMessage: "",
      toolUpdates: [],
      error: "",
      pendingPlan: null,
    });
    return next;
  },

  setGeoDataList: (list) =>
    set({ geoDataList: list, showGeoDataResults: list.length > 0 }),
  setShowGeoDataResults: (flag) => set({ showGeoDataResults: flag }),
  addGeoData: (item) =>
    set((state) => ({
      geoDataList: [...state.geoDataList, item],
      showGeoDataResults: true,
    })),
  setLoading: (flag) => set({ loading: flag }),
  setError: (error) => set({ error }),
  clearError: () => set({ error: "" }),

  addToolUpdate: (tool) =>
    set((state) => {
      const timestamp = Date.now();
      return {
        toolUpdates: [
          ...state.toolUpdates,
          {
            ...tool,
            id: buildToolUpdateId(
              tool.name,
              tool.tool_call_id,
              timestamp,
              state.toolUpdates.length,
            ),
            timestamp,
          },
        ],
      };
    }),

  updateToolStatus: (
    toolName,
    status,
    error,
    output,
    output_preview,
    is_state_update,
    output_type,
    toolCallId,
  ) =>
    set((state) => {
      const timestamp = Date.now();
      const fallbackIndex = toolCallId
        ? -1
        : state.toolUpdates
            .map((tool, index) => ({ tool, index }))
            .filter(({ tool }) => tool.name === toolName && tool.status === "running")
            .pop()?.index ?? -1;

      let updated = false;
      const nextUpdates = state.toolUpdates.map((tool, index) => {
        const matchesCallId =
          Boolean(toolCallId) && tool.tool_call_id === toolCallId;
        const matchesFallback = !toolCallId && index === fallbackIndex;

        if (!matchesCallId && !matchesFallback) {
          return tool;
        }

        updated = true;
        return {
          ...tool,
          status,
          error,
          output,
          output_preview,
          is_state_update,
          output_type,
          timestamp,
        };
      });

      if (updated) {
        return { toolUpdates: nextUpdates };
      }

      return {
        toolUpdates: [
          ...nextUpdates,
          {
            id: buildToolUpdateId(toolName, toolCallId, timestamp, nextUpdates.length),
            name: toolName,
            tool_call_id: toolCallId,
            status,
            error,
            output,
            output_preview,
            is_state_update,
            output_type,
            timestamp,
          },
        ],
      };
    }),

  appendStreamingToken: (token) =>
    set((state) => ({
      streamingMessage: state.streamingMessage + token,
    })),

  setStreamingMessage: (message) => set({ streamingMessage: message }),
  clearStreamingMessage: () => set({ streamingMessage: "" }),
  clearToolUpdates: () => set({ toolUpdates: [] }),
  setIsStreaming: (flag) => set({ isStreaming: flag }),
  setPendingPlan: (plan) => set({ pendingPlan: plan }),
}));

if (typeof window !== "undefined") {
  (window as Window & typeof globalThis & {
    useChatInterfaceStore?: typeof useChatInterfaceStore;
  }).useChatInterfaceStore = useChatInterfaceStore;
}
