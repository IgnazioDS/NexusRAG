import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatRelative } from "@/lib/utils";
import type { ActivityItem } from "@/lib/api";

const OUTCOME_DOT: Record<string, string> = {
  success: "bg-emerald-400",
  failure: "bg-red-400",
  error:   "bg-red-400",
};

const OUTCOME_LABEL: Record<string, string> = {
  success: "text-emerald-400 bg-emerald-400/10 border-emerald-400/20",
  failure: "text-red-400 bg-red-400/10 border-red-400/20",
  error:   "text-red-400 bg-red-400/10 border-red-400/20",
};

export function ActivityFeed({ items, loading }: { items?: ActivityItem[]; loading?: boolean }) {
  return (
    <div className="glow-card rounded-xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/[0.05] px-5 py-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-600">Recent Activity</p>
        {!loading && items && (
          <span className="text-[11px] text-zinc-700">{items.length} events</span>
        )}
      </div>

      {/* Content */}
      {loading ? (
        <div className="space-y-0 p-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-start gap-3 py-2.5">
              <div className="flex flex-col items-center mt-1 gap-0.5">
                <Skeleton className="h-2 w-2 rounded-full" />
                {i < 4 && <div className="w-px h-6 bg-white/[0.04]" />}
              </div>
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3.5 w-3/4" />
                <Skeleton className="h-3 w-1/3" />
              </div>
              <Skeleton className="h-4 w-14 rounded-full" />
            </div>
          ))}
        </div>
      ) : !items?.length ? (
        <p className="px-5 py-8 text-center text-[13px] text-zinc-700">No recent activity</p>
      ) : (
        <ul className="p-3">
          {items.map((item, idx) => {
            const dot = OUTCOME_DOT[item.outcome] ?? "bg-zinc-600";
            const label = OUTCOME_LABEL[item.outcome] ?? "text-zinc-500 bg-zinc-500/10 border-zinc-500/20";
            const isLast = idx === items.length - 1;

            return (
              <li key={item.id} className="group flex items-start gap-3 rounded-lg px-2 py-2.5 hover:bg-white/[0.03] transition-colors">
                {/* Timeline connector */}
                <div className="flex shrink-0 flex-col items-center pt-1">
                  <span className={cn("h-1.5 w-1.5 rounded-full", dot, idx === 0 ? "ring-2 ring-offset-1 ring-offset-[#0d0d18] ring-current" : "")} />
                  {!isLast && <div className="mt-1 w-px flex-1 min-h-[16px] bg-white/[0.05]" />}
                </div>

                {/* Content */}
                <div className="min-w-0 flex-1">
                  <p className="text-[12px] font-medium text-zinc-300 leading-snug">{item.summary}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-zinc-700">{item.event_type}</p>
                </div>

                {/* Right side */}
                <div className="flex shrink-0 flex-col items-end gap-1.5">
                  <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold", label)}>
                    {item.outcome}
                  </span>
                  <span className="text-[10px] text-zinc-700 group-hover:text-zinc-600 transition-colors">
                    {formatRelative(item.occurred_at)}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
