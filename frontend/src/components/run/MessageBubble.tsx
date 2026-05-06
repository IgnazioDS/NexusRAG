import { Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";

export type MessageRole = "user" | "assistant" | "system";

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  streaming?: boolean;
}

export function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="animate-fade-up flex justify-center py-1">
        <span className="flex items-center gap-1.5 rounded-full border border-border bg-surface-2 px-3 py-1 text-2xs text-foreground-subtle">
          <span className="h-1 w-1 rounded-full bg-brand/60" />
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "animate-fade-up flex gap-2.5",
        isUser ? "flex-row-reverse" : "flex-row",
      )}
    >
      {/* Avatar */}
      {isUser ? (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface-3 text-2xs font-semibold text-foreground-muted">
          You
        </div>
      ) : (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand/15 text-brand">
          <Sparkles className="h-3.5 w-3.5" strokeWidth={2} />
        </div>
      )}

      {/* Bubble */}
      <div
        className={cn(
          "max-w-[78%] px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap",
          isUser
            ? "rounded-2xl rounded-tr-sm bg-brand/15 border border-brand/20 text-foreground"
            : "rounded-2xl rounded-tl-sm border border-border bg-surface text-foreground-muted",
        )}
      >
        {message.content || (
          message.streaming && (
            <span className="text-foreground-faint">…</span>
          )
        )}
        {message.streaming && (
          <span
            className="ml-0.5 inline-block h-3 w-px animate-pulse rounded-sm bg-brand align-middle"
            aria-hidden
          />
        )}
      </div>
    </div>
  );
}
