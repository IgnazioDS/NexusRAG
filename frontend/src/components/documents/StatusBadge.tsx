const STATUS_STYLES: Record<string, { dot: string; text: string; bg: string; border: string }> = {
  succeeded:  { dot: "bg-emerald-400", text: "text-emerald-400", bg: "bg-emerald-400/10", border: "border-emerald-400/20" },
  processing: { dot: "bg-indigo-400 animate-pulse", text: "text-indigo-400", bg: "bg-indigo-400/10", border: "border-indigo-400/20" },
  queued:     { dot: "bg-amber-400", text: "text-amber-400", bg: "bg-amber-400/10", border: "border-amber-400/20" },
  failed:     { dot: "bg-red-400", text: "text-red-400", bg: "bg-red-400/10", border: "border-red-400/20" },
  pending:    { dot: "bg-zinc-500", text: "text-zinc-500", bg: "bg-zinc-500/10", border: "border-zinc-500/20" },
};

const DEFAULT_STYLE = STATUS_STYLES.pending;

export function StatusBadge({ status }: { status: string }) {
  const s = STATUS_STYLES[status.toLowerCase()] ?? DEFAULT_STYLE;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border ${s.border} ${s.bg} px-2 py-0.5`}>
      <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${s.dot}`} />
      <span className={`text-[11px] font-semibold ${s.text}`}>{status}</span>
    </span>
  );
}
