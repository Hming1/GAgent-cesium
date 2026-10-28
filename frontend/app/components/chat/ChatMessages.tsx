"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Loader2, ListChecks } from "lucide-react";
import { hashString } from "../../utils/hashUtil";
import MarkdownMessage from "./MarkdownMessage";

// Helper function to extract text content from message content
const extractTextContent = (content: any): string => {
  if (typeof content === "string") {
    return content;
  }

  if (Array.isArray(content)) {
    return content
      .filter((block) => block.type === "text")
      .map((block) => block.text || "")
      .join("\n");
  }

  return String(content);
};

interface ChatMessagesProps {
  conversation: any[];
  loading: boolean;
  showToolMessages?: boolean;
  expandedToolMessage?: Record<number, boolean>;
  onToggleToolMessage?: (idx: number) => void;
  disableAutoScroll?: boolean;
}

type ConversationItem =
  | { kind: "message"; msg: any; idx: number }
  | { kind: "process"; messages: Array<{ msg: any; idx: number }>; key: string };

function isToolCallMessage(msg: any) {
  return msg.type === "ai" && Boolean(
    msg.tool_calls?.length || msg.additional_kwargs?.tool_calls?.length,
  );
}

function isRenderableAiMessage(msg: any) {
  return msg.type === "ai" && extractTextContent(msg.content || "").trim().length > 0;
}

function groupProcessMessages(conversation: any[]): ConversationItem[] {
  const items: ConversationItem[] = [];
  let idx = 0;

  while (idx < conversation.length) {
    const msg = conversation[idx];

    // Keep protocol messages in state, but hide tool outputs and empty AI
    // messages without splitting the visible progress for this user turn.
    if (msg.type === "tool" || (msg.type === "ai" && !isRenderableAiMessage(msg))) {
      idx += 1;
      continue;
    }

    if (!isRenderableAiMessage(msg)) {
      items.push({ kind: "message", msg, idx });
      idx += 1;
      continue;
    }

    // Include the text accompanying tool calls as progress, skipping empty
    // protocol messages so each user turn has a stable process group.
    const run: Array<{ msg: any; idx: number }> = [];
    while (idx < conversation.length) {
      const m = conversation[idx];
      if (isRenderableAiMessage(m)) {
        run.push({ msg: m, idx });
        idx += 1;
      } else if (m.type === "tool" || m.type === "ai") {
        idx += 1;
      } else {
        break;
      }
    }

    const lastIsToolCall = isToolCallMessage(run[run.length - 1].msg);
    if (run.length > 1 || lastIsToolCall) {
      const processMessages = lastIsToolCall ? run : run.slice(0, -1);
      const first = processMessages[0];
      items.push({
        kind: "process",
        messages: processMessages,
        key: `process:${first.idx}:${processMessages.length}`,
      });
      if (!lastIsToolCall) {
        const finalMessage = run[run.length - 1];
        items.push({ kind: "message", msg: finalMessage.msg, idx: finalMessage.idx });
      }
    } else {
      const onlyMessage = run[0];
      items.push({ kind: "message", msg: onlyMessage.msg, idx: onlyMessage.idx });
    }
  }

  return items;
}

export default function ChatMessages({
  conversation,
  loading,
  showToolMessages = false,
  expandedToolMessage = {},
  onToggleToolMessage,
  disableAutoScroll = false,
}: ChatMessagesProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [expandedProcess, setExpandedProcess] = useState<Record<string, boolean>>({});
  const groupedConversation = useMemo(
    () => groupProcessMessages(conversation),
    [conversation],
  );

  // Auto-scroll to bottom with new entry, unless scroll is locked
  useEffect(() => {
    if (!disableAutoScroll) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [conversation, loading, disableAutoScroll]);

  return (
    <div className="flex-1 pb-2">
      <div className="flex flex-col space-y-3">
        {groupedConversation.map((item) => {
          if (item.kind === "process") {
            const isOpen = !!expandedProcess[item.key];
            const preview = extractTextContent(item.messages[0]?.msg.content || "");

            return (
              <div key={item.key} className="flex justify-start">
                <div className="max-w-[80%] rounded-lg rounded-tl-none border border-primary-200 bg-neutral-50/80 overflow-hidden">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-primary-50"
                    onClick={() =>
                      setExpandedProcess((prev) => ({
                        ...prev,
                        [item.key]: !prev[item.key],
                      }))
                    }
                    aria-expanded={isOpen}
                  >
                    {isOpen ? (
                      <ChevronDown size={16} className="text-primary-600 flex-shrink-0" />
                    ) : (
                      <ChevronRight size={16} className="text-primary-600 flex-shrink-0" />
                    )}
                    <ListChecks size={16} className="text-second-primary-600 flex-shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium text-primary-900">
                        执行过程
                        <span className="ml-2 text-xs font-normal text-primary-500">
                          {item.messages.length} 条进度
                        </span>
                      </div>
                      {!isOpen && preview && (
                        <div className="mt-0.5 truncate text-xs text-primary-600">
                          {preview}
                        </div>
                      )}
                    </div>
                  </button>

                  {isOpen && (
                    <div className="space-y-2 border-t border-primary-100 px-4 py-3">
                      {item.messages.map(({ msg, idx }) => {
                        const text = extractTextContent(msg.content || "");
                        // Never hash multi-MB tool/AI blobs — that freezes the UI.
                        const keySeed = `${idx}:${msg.type}:${text.slice(0, 200)}`;
                        return (
                        <div
                          key={msg.id?.trim() || hashString(`process:${keySeed}`)}
                          className="rounded-md border border-primary-100 bg-white/80 px-3 py-2"
                        >
                          <MarkdownMessage content={text} />
                        </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            );
          }

          const { msg, idx } = item;
          const textPreview = extractTextContent(msg.content || "").slice(0, 200);
          const msgKey =
            msg.id?.trim() || hashString(`${idx}:${msg.type}:${textPreview}`);

          // Handle AI message that kicked off a tool call
          if (
            msg.type === "ai" &&
            msg.additional_kwargs?.tool_calls?.length
          ) {
            if (!showToolMessages) return null;

            const call = msg.additional_kwargs.tool_calls[0];
            const isOpen = !!expandedToolMessage[idx];

            return (
              <div key={msgKey} className="flex justify-start">
                <div className="max-w px-4 py-2 rounded-lg bg-primary-100 rounded-tl-none border border-primary-300">
                  <div className="text-sm font-medium text-primary-900">
                    {"\u6b63\u5728\u4f7f\u7528\u5de5\u5177\u201c"}
                    {call.function.name}
                    {"\u201d\uff0c\u53c2\u6570\u4e3a\u201c "}
                    {call.function.arguments}
                    {"\u201d"}
                  </div>

                  <button
                    className="ml-2 px-2 py-1 bg-second-primary-600 text-white rounded text-xs hover:bg-second-primary-700"
                    onClick={() => onToggleToolMessage?.(idx)}
                  >
                    {isOpen ? "\u9690\u85cf\u7ed3\u679c" : "\u663e\u793a\u7ed3\u679c"}
                  </button>

                  {isOpen && conversation[idx + 1]?.type === "tool" && (
                    <div className="mt-2 text-sm break-words whitespace-pre-wrap text-primary-800">
                      {conversation[idx + 1].content}
                    </div>
                  )}
                </div>
              </div>
            );
          }

          // Don't render standalone tool messages
          if (msg.type === "tool") {
            return null;
          }

          // Render human/AI messages
          const isHuman = msg.type === "human";
          return (
            <div
              key={msgKey}
              className={`flex ${isHuman ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] px-4 py-2 rounded-lg ${
                  isHuman
                    ? "bg-second-primary-200 rounded-tr-none text-right border border-primary-300"
                    : "bg-neutral-50 rounded-tl-none border border-primary-200"
                }`}
              >
                {isHuman ? (
                  <div className="text-sm break-words text-primary-900">
                    {extractTextContent(msg.content)}
                  </div>
                ) : (
                  <MarkdownMessage content={extractTextContent(msg.content)} />
                )}
                <div className="text-xs text-primary-500 mt-1">
                  {isHuman
                    ? "\u4f60"
                    : msg.type === "ai"
                      ? "\u667a\u80fd\u4f53"
                      : "\u672a\u77e5"}
                </div>
              </div>
            </div>
          );
        })}

        {loading && (
          <div className="flex justify-start mb-2">
            <div className="flex items-center space-x-2 max-w-[80%] px-4 py-2 rounded-lg bg-neutral-50 rounded-tl-none border border-primary-200">
              <Loader2 size={16} className="animate-spin text-second-primary-600" />
              <span className="text-sm text-primary-700">
                GeoAgent {"\u667a\u80fd\u4f53\u6b63\u5728\u5904\u7406\u4f60\u7684\u8bf7\u6c42..."}
              </span>
            </div>
          </div>
        )}
        
        {/* Scroll target */}
        <div ref={messagesEndRef} />
      </div>
    </div>
  );
}
