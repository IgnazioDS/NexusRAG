import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn, formatNumber, percent } from "@/lib/utils";
import type { BootstrapData } from "@/lib/api";

interface QuotaBarProps {
  quota?: BootstrapData["quota_snapshot"];
  loading?: boolean;
}

function ProgressTrack({ pct, warn }: { pct: number; warn: boolean }) {
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-surface-3">
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-700 ease-out-expo",
          warn ? "bg-warning" : "bg-brand",
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

function QuotaRow({
  label,
  used,
  limit,
}: {
  label: string;
  used: number;
  limit: number | null;
}) {
  const pct = percent(used, limit);
  const warn = pct >= 80;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-foreground-muted">
          {label}
        </span>
        <span
          className={cn(
            "text-xs font-medium tabular-nums",
            warn ? "text-warning" : "text-foreground",
          )}
        >
          {limit === null ? (
            <span className="text-foreground-faint">Unlimited</span>
          ) : (
            <>
              {formatNumber(used)}
              <span className="text-foreground-faint">
                {" "}
                / {formatNumber(limit)}
              </span>
            </>
          )}
        </span>
      </div>
      {limit !== null && (
        <>
          <ProgressTrack pct={pct} warn={warn} />
          <p className="text-2xs text-right tabular-nums text-foreground-subtle">
            {Math.round(pct)}% used
          </p>
        </>
      )}
    </div>
  );
}

export function QuotaBar({ quota, loading }: QuotaBarProps) {
  if (loading || !quota) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Usage</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 pt-0">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Usage</CardTitle>
        {quota.soft_cap_reached && (
          <Badge variant="warning" className="!text-2xs">
            Throttled
          </Badge>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        <QuotaRow label="Today" used={quota.day.used} limit={quota.day.limit} />
        <div className="h-px bg-border-subtle" />
        <QuotaRow
          label="This month"
          used={quota.month.used}
          limit={quota.month.limit}
        />
      </CardContent>
    </Card>
  );
}
