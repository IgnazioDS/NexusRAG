import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { BootstrapData } from "@/lib/api";

interface QuotaBarProps {
  quota?: BootstrapData["quota_snapshot"];
  loading?: boolean;
}

function ProgressBar({ pct, warn }: { pct: number; warn: boolean }) {
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-white/[0.06]">
      <div
        className={cn(
          "h-full rounded-full transition-all duration-700",
          warn ? "progress-gradient-warn" : "progress-gradient"
        )}
        style={{ width: `${Math.min(pct, 100)}%` }}
      />
    </div>
  );
}

function QuotaRow({ label, used, limit }: { label: string; used: number; limit: number | null }) {
  const pct = limit ? Math.round((used / limit) * 100) : 0;
  const warn = pct >= 80;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium text-zinc-500">{label}</span>
        <span className={cn("text-[11px] font-semibold tabular-nums", warn ? "text-amber-400" : "text-zinc-300")}>
          {limit === null ? (
            <span className="text-zinc-600">Unlimited</span>
          ) : (
            <>
              {used.toLocaleString()}
              <span className="text-zinc-600"> / {limit.toLocaleString()}</span>
            </>
          )}
        </span>
      </div>
      {limit !== null && (
        <div className="space-y-1">
          <ProgressBar pct={pct} warn={warn} />
          <p className={cn("text-[10px] text-right tabular-nums", warn ? "text-amber-500/70" : "text-zinc-700")}>
            {pct}% used
          </p>
        </div>
      )}
    </div>
  );
}

export function QuotaBar({ quota, loading }: QuotaBarProps) {
  if (loading || !quota) {
    return (
      <div className="glow-card rounded-xl p-5 space-y-5">
        <div className="flex items-center justify-between">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-4 w-12 rounded-full" />
        </div>
        <div className="space-y-3">
          <Skeleton className="h-8 w-full rounded-lg" />
          <Skeleton className="h-8 w-full rounded-lg" />
        </div>
      </div>
    );
  }

  return (
    <div className="glow-card rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-600">Usage Quota</p>
        {quota.soft_cap_reached && (
          <span className="rounded-full border border-amber-500/20 bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-400">
            Throttled
          </span>
        )}
      </div>

      <div className="space-y-4">
        <QuotaRow label="Today" used={quota.day.used} limit={quota.day.limit} />
        <div className="h-px bg-white/[0.04]" />
        <QuotaRow label="This month" used={quota.month.used} limit={quota.month.limit} />
      </div>
    </div>
  );
}
