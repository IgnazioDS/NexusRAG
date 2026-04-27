"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  FileText,
  RefreshCw,
  RotateCcw,
  Search,
} from "lucide-react";
import { toast } from "sonner";
import {
  fetchDocuments,
  reindexDocument,
  type DocumentRow,
} from "@/lib/api";
import { StatusBadge } from "./StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDebounce } from "@/lib/hooks";
import { formatDate, truncate } from "@/lib/utils";

const STATUS_OPTIONS = ["all", "queued", "processing", "succeeded", "failed"];

export function DocumentsTable() {
  const [rows, setRows] = useState<DocumentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");
  const debouncedQ = useDebounce(q, 250);
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
          q: debouncedQ || undefined,
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
    [debouncedQ, status],
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
        prev.map((r) => (r.id === id ? { ...r, status: "queued" } : r)),
      );
      toast.success("Reindex queued", {
        description: `Document ${truncate(id, 16)} will be re-embedded shortly.`,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Reindex failed";
      toast.error("Reindex failed", { description: msg });
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
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-48">
          <Search className="absolute left-2.5 top-1/2 h-3 w-3 -translate-y-1/2 text-foreground-faint pointer-events-none" />
          <Input
            placeholder="Search documents…"
            className="pl-8"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <Select value={status} onValueChange={setStatus}>
          <SelectTrigger className="w-36">
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
          variant="secondary"
          size="default"
          onClick={() => load(undefined)}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-md border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
          <span className="h-1.5 w-1.5 rounded-full bg-danger shrink-0" />
          {error}
        </div>
      )}

      {/* Table */}
      <Card className="overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border">
              <th className="px-4 py-2.5 text-left text-2xs font-medium uppercase tracking-wider text-foreground-faint">
                Filename
              </th>
              <th className="px-4 py-2.5 text-left text-2xs font-medium uppercase tracking-wider text-foreground-faint">
                Corpus
              </th>
              <th className="px-4 py-2.5 text-left text-2xs font-medium uppercase tracking-wider text-foreground-faint">
                Status
              </th>
              <th className="px-4 py-2.5 text-left text-2xs font-medium uppercase tracking-wider text-foreground-faint hidden md:table-cell">
                Created
              </th>
              <th className="px-4 py-2.5 text-right text-2xs font-medium uppercase tracking-wider text-foreground-faint">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle">
            {loading
              ? Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <Skeleton className="h-7 w-7 rounded-md" />
                        <div className="space-y-1.5">
                          <Skeleton className="h-3 w-40" />
                          <Skeleton className="h-2.5 w-24" />
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Skeleton className="h-3 w-16" />
                    </td>
                    <td className="px-4 py-3">
                      <Skeleton className="h-4 w-20 rounded-full" />
                    </td>
                    <td className="px-4 py-3 hidden md:table-cell">
                      <Skeleton className="h-3 w-24" />
                    </td>
                    <td className="px-4 py-3" />
                  </tr>
                ))
              : rows.length === 0
              ? (
                <tr>
                  <td colSpan={5} className="p-0">
                    <EmptyState
                      icon={FileText}
                      title="No documents"
                      description={
                        q || status !== "all"
                          ? "No documents match your filters."
                          : "Once you ingest your first document it'll appear here."
                      }
                    />
                  </td>
                </tr>
              )
              : rows.map((row) => (
                  <tr
                    key={row.id}
                    className="group hover:bg-surface-2 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-surface-2 text-foreground-faint">
                          <FileText className="h-3.5 w-3.5" strokeWidth={1.75} />
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-foreground truncate max-w-xs leading-tight">
                            {row.filename}
                          </p>
                          <p className="mt-0.5 font-mono text-2xs text-foreground-faint truncate">
                            {truncate(row.id, 18)}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-foreground-muted">
                      {row.corpus_id}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={row.status} />
                    </td>
                    <td className="px-4 py-3 text-xs text-foreground-subtle hidden md:table-cell">
                      {formatDate(row.created_at)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Button
                        size="icon-sm"
                        variant="ghost"
                        onClick={() => handleReindex(row.id)}
                        disabled={reindexing.has(row.id)}
                        title="Reindex"
                      >
                        <RotateCcw
                          className={
                            reindexing.has(row.id) ? "animate-spin" : ""
                          }
                        />
                      </Button>
                    </td>
                  </tr>
                ))}
          </tbody>
        </table>
      </Card>

      {/* Pagination */}
      <div className="flex items-center justify-between px-1">
        <p className="text-xs text-foreground-subtle tabular-nums">
          {rows.length} {rows.length === 1 ? "document" : "documents"}
        </p>
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="outline"
            onClick={prevPage}
            disabled={cursorStack.length === 0}
          >
            <ChevronLeft />
            Prev
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={nextPage}
            disabled={!hasMore}
          >
            Next
            <ChevronRight />
          </Button>
        </div>
      </div>
    </div>
  );
}
