"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownMessageProps {
  content: string;
  className?: string;
}

export default function MarkdownMessage({ content, className = "" }: MarkdownMessageProps) {
  return (
    <div className={`text-sm break-words chat-markdown text-primary-900 ${className}`.trim()}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}