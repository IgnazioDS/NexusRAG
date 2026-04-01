"use client";
import { useCallback, useEffect, useState } from "react";
import { Search, RefreshCw, ChevronLeft, ChevronRight, RotateCcw, FileText } from "lucide-react";
import { fetchDocuments, reindexDocument, type DocumentRow } from "@/lib/api";
import { StatusBadge } from "./StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { formatDate } from "@/lib/utils";

const STATUS_OPTIONS = ["all", "queued", "processing", "succeeded", "failed"];

export function DocumentsTable() {
  const [rows, setRows] = useState<DocumentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [cursor, setCursor] = useState<string | undefined>();
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [reindexing, setReindexing] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (cur?: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetchDocuments({
          q: q || undefined,
          status: status !== "all" ? status : undefined,
          cursor: cur,
          limit: 20,
        });
        setRows(res.items);
        setHasMore(res.page.has_more);
        setCursor(res.page.next_cursor ?? undefined);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load documents");
      } finally {
        setLoading(false);
      }
    },
    [q, status]
  );

  useEffect(() => {
    setCursorStack([]);
    load(undefined);
  }, [load]);

  function nextPage() {
    if (!cursor) return;
    setCursorStack((s) => [...s, cursor]);
    load(cursor);
  }

  function prevPage() {
    const stack = [...cursorStack];
    const prev = stack.pop();
    setCursorStack(stack);
    load(prev);
  }

  async function handleReindex(id: string) {
    setReindexing((s) => new Set(s).add(id));
    try {
      await reindexDocument(id);
      setRows((prev) =>
        prev.map((r) => (r.id === id ? { ...r, status: "queued" } : r))
      );
    } finally {
      setReindexing((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
    }
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-600 pointer-events-none" />
          <Input
            placeholder="Search documents…"
            className="pl-9 bg-white/[0.03] border-white/[0.08] text-zinc-200 placeholder:text-zinc-700 focus:border-indigo-500/40 focus:bg-white/[0.05]"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-36 bg-white/[0.03] border-white/[0.08] text-zinc-300">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            {STATUS_OPTIONS.map((s) => (
              <SelectItem key={s} value={s}>
                {s === "all" ? "All statuses" : s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="sm"
          onClick={() => load(undefined)}
          className="border-white/[0.08] bg-white/[0.03] text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-200 gap-1.5"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-red-500/20 bg-red-500/[0.07] px-4 py-3 text-[13px] text-red-400">
          <span className="h-1.5 w-1.5 rounded-full bg-red-400 shrink-0" />
          {error}
        </div>
      )}

      {/* Table */}
      <div className="glow-card overflow-hidden rounded-xl">
        <table className="w-full">
          <thead>
            <tr className="border-b border-white/[0.06]">
              <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.1em] text-zinc-700">Filename</th>
              <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.1em] text-zinc-700">Corpus</th>
              <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.1em] text-zinc-700">Status</th>
              <th className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-[0.1em] text-zinc-700 hidden md:table-cell">Created</th>
              <th className="px-4 py-3 text-right text-[10px] font-semibold uppercase tracking-[0.1em] text-zinc-700">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {loading
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <Skeleton className="h-7 w-7 rounded-lg" />
                        <div className="space-y-1.5">
                          <Skeleton className="h-3.5 w-40" />
                          <Skeleton className="h-2.5 w-24" />
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3.5"><Skeleton className="h-3.5 w-16" /></td>
                    <td className="px-4 py-3.5"><Skeleton className="h-5 w-22 rounded-full" /></td>
                    <td className="px-4 py-3.5 hidden md:table-cell"><Skeleton className="h-3.5 w-28" /></td>
                    <td className="px-4 py-3.5" />
                  </tr>
                ))
              : rows.length === 0
              ? (
                <tr>
                  <td colSpan={5} className="px-4 py-16 text-center">
                    <FileText className="mx-auto mb-3 h-8 w-8 text-zinc-800" />
                    <p className="text-[13px] text-zinc-700">No documents found</p>
                  </td>
                </tr>
              )
              : rows.map((row) => (
                  <tr key={row.id} className="group hover:bg-white/[0.025] transition-colors">
                    <td className="px-4 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-400">
                          <FileText className="h-3.5 w-3.5" strokeWidth={1.75} />
                        </div>
                        <div className="min-w-0">
                          <p className="text-[13px] font-medium text-zinc-200 truncate max-w-xs leading-tight">
                            {row.filename}
                          </p>
                          <p className="mt-0.5 font-mono text-[10px] text-zinc-700 truncate">{row.id}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3.5 font-mono text-[12px] text-zinc-500">{row.corpus_id}</td>
                    <td className="px-4 py-3.5"><StatusBadge status={row.status} /></td>
                    <td className="px-4 py-3.5 text-[12px] text-zinc-600 hidden md:table-cell">
                      {formatDate(row.created_at)}
                    </td>
                    <td className="px-4 py-3.5 text-right">
                      <button
                        onClick={() => handleReindex(row.id)}
                        disabled={reindexing.has(row.id)}
                        title="Reindex"
                        className="inline-flex h-7 w-7 items-center justify-center rounded-lg text-zinc-700 transition-all hover:bg-indigo-500/10 hover:text-indigo-400 disabled:opacity-50"
                      >
                        <RotateCcw className={`h-3.5 w-3.5 ${reindexing.has(row.id) ? "animate-spin" : ""}`} />
                      </button>
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between px-1">
        <p className="text-[11px] text-zinc-700">{rows.length} documents</p>
        <div className="flex items-center gap-1.5">
          <button
            onClick={prevPage}
            disabled={cursorStack.length === 0}
            className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-[11px] text-zinc-400 transition-all hover:bg-white/[0.06] hover:text-zinc-200 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <ChevronLeft className="h-3.5 w-3.5" /> Prev
          </button>
          <button
            onClick={nextPage}
            disabled={!hasMore}
            className="inline-flex h-7 items-center gap-1 rounded-lg border border-white/[0.08] bg-white/[0.03] px-2.5 text-[11px] text-zinc-400 transition-all hover:bg-white/[0.06] hover:text-zinc-200 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            Next <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
