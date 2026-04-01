"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Send, Square, ChevronDown, Cpu } from "lucide-react";
import { streamRun } from "@/lib/sse";
import { MessageBubble, type Message } from "./MessageBubble";
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
      content: "Connected to NexusRAG — enter a query to begin",
    },
  ]);
  const [input, setInput] = useState("");
  const [corpusId, setCorpusId] = useState(DEFAULT_CORPUS);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sessionId = useRef(`session-${randomId()}`);

  useEffect(() => {
    if (atBottom) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, atBottom]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
  }

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    const userMsg: Message = { id: randomId(), role: "user", content: text };
    const assistantId = randomId();
    const assistantMsg: Message = { id: assistantId, role: "assistant", content: "", streaming: true };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setStreaming(true);
    setError(null);
    setAtBottom(true);

    try {
      await streamRun(
        { session_id: sessionId.current, corpus_id: corpusId, message: text, top_k: 5 },
        (event) => {
          if (controller.signal.aborted) return;
          if (event.type === "token.delta") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: m.content + event.data.token } : m
              )
            );
          } else if (event.type === "message.final") {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId ? { ...m, content: event.data.text, streaming: false } : m
              )
            );
          } else if (event.type === "error") {
            setError(`${event.data.code}: ${event.data.message}`);
          }
        },
        controller.signal
      );
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(e instanceof Error ? e.message : "Stream error");
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, streaming: false } : m))
        );
      }
    } finally {
      if (!controller.signal.aborted) setStreaming(false);
    }
  }, [input, streaming, corpusId]);

  function stop() {
    abortRef.current?.abort();
    setStreaming(false);
    setMessages((prev) => prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)));
  }

  return (
    <div className="flex h-full flex-col">
      {/* Config bar */}
      <div className="flex items-center gap-3 border-b border-white/[0.06] bg-white/[0.02] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <Cpu className="h-3.5 w-3.5 text-zinc-600" strokeWidth={1.75} />
          <span className="text-[11px] text-zinc-600">Corpus</span>
          <input
            className="h-6 w-28 rounded-md border border-white/[0.08] bg-white/[0.03] px-2 font-mono text-[11px] text-zinc-300 outline-none placeholder:text-zinc-700 focus:border-indigo-500/40 focus:bg-white/[0.05]"
            value={corpusId}
            onChange={(e) => setCorpusId(e.target.value)}
            placeholder="c1"
          />
        </div>

        <div className="ml-auto flex items-center gap-2">
          <span
            className={cn(
              "h-1.5 w-1.5 rounded-full transition-colors",
              streaming ? "bg-indigo-400 animate-pulse" : "bg-zinc-700"
            )}
          />
          <span className="text-[11px] text-zinc-700">
            {streaming ? "Streaming…" : "Ready"}
          </span>
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="relative flex-1 overflow-y-auto px-5 py-5 space-y-4"
      >
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {error && (
          <div className="msg-enter flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/[0.07] px-4 py-2.5 text-[12px] text-red-400">
            <span className="h-1.5 w-1.5 rounded-full bg-red-400 shrink-0" />
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Scroll-to-bottom button */}
      {!atBottom && (
        <div className="absolute bottom-20 right-6 z-10">
          <button
            onClick={() => { setAtBottom(true); bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }}
            className="flex h-8 w-8 items-center justify-center rounded-full border border-white/[0.08] bg-[#0d0d18] shadow-lg text-zinc-400 hover:text-zinc-200 transition-colors"
          >
            <ChevronDown className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Input */}
      <div className="border-t border-white/[0.06] px-4 py-3">
        <div className="flex items-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.03] px-3 py-2 focus-within:border-indigo-500/40 focus-within:bg-white/[0.05] transition-all">
          <input
            className="flex-1 bg-transparent text-[13px] text-zinc-200 outline-none placeholder:text-zinc-700"
            placeholder="Ask anything about your documents…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
            }}
            disabled={streaming}
          />
          {streaming ? (
            <button
              onClick={stop}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
              title="Stop"
            >
              <Square className="h-3.5 w-3.5" />
            </button>
          ) : (
            <button
              onClick={send}
              disabled={!input.trim()}
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-white shadow-lg shadow-indigo-500/20 transition-all hover:bg-indigo-500 disabled:opacity-30 disabled:cursor-not-allowed"
              title="Send"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        <p className="mt-1.5 text-center text-[10px] text-zinc-800">
          Enter to send · Shift+Enter for newline
        </p>
      </div>
    </div>
  );
}
