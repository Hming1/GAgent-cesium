import type { ChatMessage } from "../models/geodatamodel";

/** Hard caps so a single bad tool payload cannot freeze the chat UI. */
export const MAX_TOOL_CONTENT_CHARS = 4000;
export const MAX_SSE_EVENT_CHARS = 1_500_000;

function truncateText(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max)}\n...[truncated ${value.length - max} chars]`;
}

function summarizeToolInput(input: unknown): Record<string, unknown> | undefined {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    return undefined;
  }
  const record = input as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const key of [
    "operation",
    "operator",
    "query",
    "field",
    "fields",
    "target_layer_name",
    "target_layer_names",
    "layer_names",
    "layer_name",
    "table_name",
    "schema_name",
    "analysis_goal",
    "max_features_per_layer",
    "row_limit",
    "add_to_map",
    "fill_color",
    "stroke_color",
    "fill_opacity",
  ]) {
    if (record[key] !== undefined) {
      out[key] = record[key];
    }
  }
  if (typeof record.code === "string") {
    out.code_chars = record.code.length;
  }
  return out;
}

/** Keep protocol messages, but strip multi-MB tool bodies before React state. */
export function sanitizeChatMessages(messages: ChatMessage[] | undefined | null): ChatMessage[] {
  if (!Array.isArray(messages)) return [];
  return messages.map((msg) => {
    const next: ChatMessage = { ...msg };
    if (typeof next.content === "string" && next.type === "tool") {
      next.content = truncateText(next.content, MAX_TOOL_CONTENT_CHARS);
    }
    if (Array.isArray(next.tool_calls)) {
      next.tool_calls = next.tool_calls.map((call: any) => {
        if (!call || typeof call !== "object") return call;
        const cloned = { ...call, args: call.args ? { ...call.args } : call.args };
        if (cloned.args && typeof cloned.args.code === "string") {
          cloned.args = {
            ...cloned.args,
            code: truncateText(cloned.args.code, 500),
            code_truncated: true,
          };
        }
        if (
          cloned.function?.arguments &&
          typeof cloned.function.arguments === "string" &&
          cloned.function.arguments.length > 800
        ) {
          cloned.function = {
            ...cloned.function,
            arguments: truncateText(cloned.function.arguments, 800),
          };
        }
        return cloned;
      });
    }
    return next;
  });
}

export function sanitizeToolStartInput(input: unknown): Record<string, unknown> | undefined {
  return summarizeToolInput(input);
}

export function isOversizedSsePayload(eventData: string): boolean {
  return eventData.length > MAX_SSE_EVENT_CHARS;
}
