import { Activity } from "lucide-react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { StatusDot } from "@/components/ui/status-dot";
import { EmptyState } from "@/components/ui/empty-state";
import { formatRelative } from "@/lib/utils";
import type { ActivityItem } from "@/lib/api";

const OUTCOME_TONE: Record<
  string,
  { dot: "success" | "danger" | "muted" | "warning"; badge: "success" | "danger" | "muted" | "warning" }
> = {
  success: { dot: "success", badge: "success" },
  failure: { dot: "danger", badge: "danger" },
  error: { dot: "danger", badge: "danger" },
  warning: { dot: "warning", badge: "warning" },
};

export function ActivityFeed({
  items,
  loading,
}: {
  items?: ActivityItem[];
  loading?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between border-b border-border-subtle">
        <CardTitle>Recent activity</CardTitle>
        {!loading && items && (
          <span className="text-2xs text-foreground-faint tabular-nums">
            {items.length} events
          </span>
        )}
      </CardHeader>
      {loading ? (
        <CardContent className="space-y-3 pt-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="flex items-start gap-3">
              <Skeleton className="h-2 w-2 mt-1.5 rounded-full" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3 w-3/4" />
                <Skeleton className="h-2.5 w-1/3" />
              </div>
              <Skeleton className="h-4 w-14 rounded-full" />
            </div>
          ))}
        </CardContent>
      ) : !items?.length ? (
        <EmptyState
          icon={Activity}
          title="No activity yet"
          description="Once requests start flowing, they'll appear here."
          className="py-8"
        />
      ) : (
        <ul className="px-2 py-2">
          {items.map((item) => {
            const tone =
              OUTCOME_TONE[item.outcome.toLowerCase()] ??
              ({ dot: "muted", badge: "muted" } as const);
            return (
              <li
                key={item.id}
                className="group flex items-start gap-3 rounded-md px-3 py-2 hover:bg-surface-2 transition-colors"
              >
                <div className="pt-1.5">
                  <StatusDot tone={tone.dot} size="sm" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-foreground leading-snug">
                    {item.summary}
                  </p>
                  <p className="mt-0.5 font-mono text-2xs text-foreground-faint truncate">
                    {item.event_type}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <Badge variant={tone.badge}>{item.outcome}</Badge>
                  <span className="text-2xs text-foreground-subtle tabular-nums">
                    {formatRelative(item.occurred_at)}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
