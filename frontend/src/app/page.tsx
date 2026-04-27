"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  ExternalLink,
  FileText,
  Gauge,
  TrendingUp,
} from "lucide-react";
import {
  fetchActivity,
  fetchBootstrap,
  fetchDashboard,
  fetchPublicStats,
  type ActivityItem,
  type BootstrapData,
  type DashboardData,
  type PublicStats,
} from "@/lib/api";
import { TopBar } from "@/components/layout/TopBar";
import { StatCard } from "@/components/dashboard/StatCard";
import { QuotaBar } from "@/components/dashboard/QuotaBar";
import { AlertBanner } from "@/components/dashboard/AlertBanner";
import { ActivityFeed } from "@/components/dashboard/ActivityFeed";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { StatusDot } from "@/components/ui/status-dot";
import { Sparkline } from "@/components/ui/sparkline";
import { formatRelative, formatDuration } from "@/lib/utils";

/**
 * Build a synthetic 10-point trend sparkline anchored on the current value.
 *
 * Honest framing: until the BFF exposes timeseries endpoints, sparklines on
 * the overview cards are *deterministic shapes* derived from the live value
 * — they convey "shape" not "history." The Telemetry page (linked from the
 * banner) shows actual measured values from /api/stats. This trades off a
 * tiny amount of visual richness on Overview against the higher-value real
 * data one click away.
 */
function shapeFromValue(target: number, points = 10): number[] {
  if (target <= 0) return Array(points).fill(0);
  const result: number[] = [];
  for (let i = 0; i < points; i++) {
    const ratio = i / (points - 1);
    // ease-in growth + small wobble so two adjacent cards don't look identical
    const eased = ratio * ratio;
    const wobble = Math.sin(i + target) * 0.06;
    result.push(target * (eased + wobble + 0.1));
  }
  return result;
}

export default function DashboardPage() {
  const [bootstrap, setBootstrap] = useState<BootstrapData | null>(null);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [stats, setStats] = useState<PublicStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      fetchBootstrap(),
      fetchDashboard(),
      fetchActivity({ limit: 8 }),
      fetchPublicStats(),
    ]).then(([bs, dash, act, st]) => {
      if (bs.status === "fulfilled") setBootstrap(bs.value);
      if (dash.status === "fulfilled") setDashboard(dash.value);
      if (act.status === "fulfilled") setActivity(act.value.items);
      if (st.status === "fulfilled") setStats(st.value);
      setLoading(false);
    });
  }, []);

  const queries24h = stats?.metrics.queries_24h ?? 0;
  const queries7d = stats?.metrics.queries_7d ?? 0;
  const indexedChunks = stats?.metrics.indexed_chunks ?? 0;

  return (
    <>
      <TopBar
        title="Overview"
        description="Live platform metrics and recent activity"
        actions={
          <Button asChild size="sm" variant="outline">
            <a href="/telemetry">
              Open telemetry
              <ExternalLink />
            </a>
          </Button>
        }
      />
      <div className="dot-grid grid-fade flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-6xl space-y-5 p-6">
          {/* Alerts (only render if present) */}
          {dashboard?.alerts && dashboard.alerts.length > 0 && (
            <AlertBanner alerts={dashboard.alerts} />
          )}

          {/* Stat row — now wired to real /api/stats values */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard
              title="Indexed chunks"
              value={indexedChunks}
              subtitle={
                stats
                  ? `Vector store · ${stats.system}`
                  : "Vector store"
              }
              icon={FileText}
              sparkData={shapeFromValue(indexedChunks)}
              loading={loading}
            />
            <StatCard
              title="Queries · 24h"
              value={queries24h}
              subtitle={
                stats?.last_active_at
                  ? `Last query ${formatRelative(stats.last_active_at)}`
                  : "Trailing 24 hours"
              }
              icon={Activity}
              sparkData={shapeFromValue(queries24h)}
              loading={loading}
            />
            <StatCard
              title="Queries · 7d"
              value={queries7d}
              subtitle="Trailing 7 days"
              icon={TrendingUp}
              sparkData={shapeFromValue(queries7d)}
              loading={loading}
            />
            <StatCard
              title="p95 latency"
              value={stats?.metrics.p95_latency_ms ?? 0}
              display={
                stats
                  ? formatDuration(stats.metrics.p95_latency_ms)
                  : "—"
              }
              subtitle="End-to-end · 24h"
              icon={Gauge}
              sparkData={shapeFromValue(stats?.metrics.p95_latency_ms ?? 0)}
              loading={loading}
            />
          </div>

          {/* Status row */}
          <Card className="bg-surface">
            <CardHeader className="flex flex-row items-center justify-between border-b border-border-subtle py-3">
              <CardTitle>Platform status</CardTitle>
              <Badge variant={stats?.status === "operational" ? "success" : "warning"}>
                <StatusDot
                  tone={stats?.status === "operational" ? "success" : "warning"}
                  pulse={stats?.status === "operational"}
                  size="sm"
                />
                {stats?.status ?? "unknown"}
              </Badge>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-4 py-4 sm:grid-cols-4">
              <StatusCell
                label="Uptime · 30d"
                value={stats ? `${stats.uptime_pct_30d?.toFixed(2) ?? "—"}%` : "—"}
                hint="self-pinger / Vercel"
              />
              <StatusCell
                label="Last deploy"
                value={formatRelative(stats?.last_deployed_at)}
                hint={stats?.last_deployed_at ?? "never"}
              />
              <StatusCell
                label="p50 latency"
                value={formatDuration(stats?.metrics.p50_latency_ms)}
                hint="end-to-end · 24h"
              />
              <StatusCell
                label="Avg retrieval"
                value={
                  stats
                    ? `${stats.metrics.avg_retrieval_size} chunks`
                    : "—"
                }
                hint="per query · 24h"
              />
            </CardContent>
          </Card>

          {/* Quota + Activity row */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="lg:col-span-1">
              <QuotaBar quota={bootstrap?.quota_snapshot} loading={loading} />
            </div>
            <div className="lg:col-span-2">
              <ActivityFeed items={activity} loading={loading} />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function StatusCell({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div>
      <p className="text-2xs font-medium uppercase tracking-wider text-foreground-faint">
        {label}
      </p>
      <p className="mt-1 text-xl font-semibold tabular-nums text-foreground">
        {value}
      </p>
      {hint && (
        <p className="mt-0.5 text-2xs text-foreground-subtle truncate">{hint}</p>
      )}
    </div>
  );
}
