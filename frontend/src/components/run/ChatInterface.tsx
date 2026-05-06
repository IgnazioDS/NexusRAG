"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, Cpu, Send, Square } from "lucide-react";
import { toast } from "sonner";
import { streamRun } from "@/lib/sse";
import { MessageBubble, type Message } from "./MessageBubble";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/ui/status-dot";
import { cn } from "@/lib/utils";

function randomId() {
  return Math.random().toString(36).slice(2);
}

const DEFAULT_CORPUS = process.env.NEXT_PUBLIC_DEFAULT_CORPUS_ID ?? "c1";

export function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "system",
      content: "Connected to NexusRAG — ask anything to begin",
    },
  ]);
  const [input, setInput] = useState("");
  const [corpusId, setCorpusId] = useState(DEFAULT_CORPUS);
  const [streaming, setStreaming] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sessionId = useRef(`session-${randomId()}`);

  useEffect(() => {
    if (atBottom) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, atBottom]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  }

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const userMsg: Message = { id: randomId(), role: "user", content: text };
    const assistantId = randomId();
    const assistantMsg: Message = {
      id: assistantId,
      role: "assistant",
      content: "",
      streaming: true,
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setStreaming(true);
    setAtBottom(true);

    try {
      await streamRun(
        {
          session_id: sessionId.current,
          corpus_id: corpusId,
          message: text,
          top_k: 5,
        },
        (event) => {
          if (controller.signal.aborted) return;
          if (event.type === "token.delta") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: m.content + event.data.token }
                  : m,
              ),
            );
          } else if (event.type === "message.final") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? { ...m, content: event.data.text, streaming: false }
                  : m,
              ),
            );
          } else if (event.type === "error") {
            toast.error(event.data.code, { description: event.data.message });
          }
        },
        controller.signal,
      );
    } catch (e) {
      if (!controller.signal.aborted) {
        const msg = e instanceof Error ? e.message : "Stream error";
        toast.error("Stream failed", { description: msg });
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, streaming: false } : m,
          ),
        );
      }
    } finally {
      if (!controller.signal.aborted) {
        setStreaming(false);
        inputRef.current?.focus();
      }
    }
  }, [input, streaming, corpusId]);

  function stop() {
    abortRef.current?.abort();
    setStreaming(false);
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Config bar */}
      <div className="flex items-center gap-3 border-b border-border-subtle bg-surface px-4 py-2">
        <div className="flex items-center gap-2">
          <Cpu
            className="h-3.5 w-3.5 text-foreground-faint"
            strokeWidth={1.75}
          />
          <span className="text-xs text-foreground-subtle">Corpus</span>
          <input
            className="h-6 w-32 rounded-md border border-border bg-surface px-2 font-mono text-xs text-foreground-muted outline-none placeholder:text-foreground-faint focus:border-brand/40"
            value={corpusId}
            onChange={(e) => setCorpusId(e.target.value)}
            placeholder="c1"
          />
        </div>

        <div className="ml-auto flex items-center gap-2">
          <StatusDot
            tone={streaming ? "info" : "muted"}
            pulse={streaming}
            size="sm"
          />
          <span className="text-xs text-foreground-subtle">
            {streaming ? "Streaming" : "Ready"}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div className="relative flex-1 overflow-hidden">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="absolute inset-0 overflow-y-auto px-5 py-5 space-y-4"
        >
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          <div ref={bottomRef} />
        </div>

        {!atBottom && (
          <div className="absolute bottom-4 right-5 z-10">
            <Button
              size="icon-sm"
              variant="secondary"
              onClick={() => {
                setAtBottom(true);
                bottomRef.current?.scrollIntoView({ behavior: "smooth" });
              }}
              className="rounded-full shadow-elevated"
              aria-label="Scroll to bottom"
            >
              <ChevronDown />
            </Button>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-border-subtle px-4 py-3 bg-surface">
        <div
          className={cn(
            "flex items-end gap-2 rounded-md border border-border bg-surface px-3 py-2",
            "transition-colors duration-150",
            "focus-within:border-brand/40",
          )}
        >
          <textarea
            ref={inputRef}
            rows={1}
            className="flex-1 max-h-32 resize-none bg-transparent text-sm text-foreground outline-none placeholder:text-foreground-faint leading-relaxed py-0.5"
            placeholder="Ask anything about your documents…"
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              const el = e.currentTarget;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 128)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            disabled={streaming}
          />
          {streaming ? (
            <Button
              size="icon-sm"
              variant="danger"
              onClick={stop}
              aria-label="Stop streaming"
            >
              <Square />
            </Button>
          ) : (
            <Button
              size="icon-sm"
              variant="primary"
              onClick={send}
              disabled={!input.trim()}
              aria-label="Send"
            >
              <Send />
            </Button>
          )}
        </div>
        <p className="mt-1.5 text-center text-2xs text-foreground-faint">
          Enter to send · Shift + Enter for newline
        </p>
      </div>
    </div>
  );
}
