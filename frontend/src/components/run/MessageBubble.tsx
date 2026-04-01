import { cn } from "@/lib/utils";
import { Zap } from "lucide-react";

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
      <div className="msg-enter flex justify-center py-1">
        <span className="flex items-center gap-1.5 rounded-full border border-white/[0.06] bg-white/[0.03] px-3 py-1 text-[11px] text-zinc-600">
          <span className="h-1 w-1 rounded-full bg-indigo-500/60" />
          {message.content}
        </span>
      </div>
    );
  }

  return (
    <div className={cn("msg-enter flex gap-2.5", isUser ? "flex-row-reverse" : "flex-row")}>
      {/* Avatar */}
      {isUser ? (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-[10px] font-bold text-white">
          U
        </div>
      ) : (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 shadow-lg shadow-indigo-500/20">
          <Zap className="h-3.5 w-3.5 text-white" strokeWidth={2.5} />
        </div>
      )}

      {/* Bubble */}
      <div
        className={cn(
          "max-w-[78%] rounded-2xl px-4 py-3 text-[13px] leading-relaxed",
          isUser
            ? "rounded-tr-sm bg-indigo-600 text-white shadow-lg shadow-indigo-500/20"
            : "rounded-tl-sm border border-white/[0.07] bg-white/[0.04] text-zinc-200"
        )}
      >
        {message.content || (message.streaming && <span className="text-zinc-600">…</span>)}
        {message.streaming && (
          <span className="ml-0.5 inline-block h-[14px] w-[2px] animate-pulse rounded-sm bg-indigo-400 align-middle" />
        )}
      </div>
    </div>
  );
}
