"use client";

import { templatesForMessageType } from "../logic";
import type { StarterTemplate } from "../types";
import type { MessageType } from "../../event-message/types";

export default function TemplatePicker({
  messageType,
  onSelect,
}: {
  messageType: MessageType;
  onSelect: (template: StarterTemplate) => void;
}) {
  const templates = templatesForMessageType(messageType);
  if (templates.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-[var(--color-text-muted)]">시작 템플릿:</span>
      {templates.map((template) => (
        <button
          key={template.id}
          type="button"
          onClick={() => onSelect(template)}
          className="tap-target rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2.5 py-1 text-xs hover:bg-[var(--color-surface-muted)]"
        >
          {template.label_ko}
        </button>
      ))}
    </div>
  );
}
