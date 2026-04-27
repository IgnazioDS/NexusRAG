"use client";

import { useState } from "react";
import {
  Activity,
  CheckCircle2,
  Clock,
  Database,
  Gauge,
  Hourglass,
  RefreshCw,
} from "lucide-react";
import { fetchPublicStats, type PublicStats } from "@/lib/api";
import { TopBar } from "@/components/layout/TopBar";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { StatusDot } from "@/components/ui/status-dot";
import { CodeBlock } from "@/components/ui/code-block";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePolling } from "@/lib/hooks";
import {
  formatDate,
  formatDuration,
  formatNumber,
  formatRelative,
} from "@/lib/utils";

const POLL_INTERVAL_MS = 30_000;

export default function TelemetryPage() {
  const { data: stats, loading, error, refetch } = usePolling<PublicStats>(
    fetchPublicStats,
    POLL_INTERVAL_MS,
  );
  const [tab, setTab] = useState("overview");

  return (
    <>
      <TopBar
        title="Telemetry"
        description="Live readout of the public /api/stats contract"
        actions={
          <Button size="sm" variant="outline" onClick={refetch}>
            <RefreshCw />
            Refresh
          </Button>
        }
      />
      <div className="flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-6xl space-y-5 p-6">
          {/* Header status row */}
          <Card>
            <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <StatusDot
                  tone={
                    stats?.status === "operational"
                      ? "success"
                      : stats?.status === "degraded"
                      ? "warning"
                      : "muted"
                  }
                  pulse={stats?.status === "operational"}
                  size="lg"
                />
                <div>
                  <p className="text-sm font-semibold text-foreground tracking-tight">
                    {stats?.system ?? "nexusrag"}
                  </p>
                  <p className="text-xs text-foreground-muted">
                    {stats
                      ? `${stats.status} · schema v${stats.schema_version}`
                      : "loading…"}
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={stats?.mode === "live" ? "brand" : "muted"}>
                  {stats?.mode ?? "live"}
                </Badge>
                <Badge variant="outline">
                  uptime {stats?.uptime_pct_30d?.toFixed(2) ?? "—"}%
                </Badge>
                <Badge variant="outline">
                  generated {formatRelative(stats?.generated_at)}
                </Badge>
              </div>
            </CardContent>
          </Card>

          {error && !stats && (
            <Card className="border-danger/30 bg-danger/5">
              <CardContent className="flex items-start gap-3 p-4">
                <StatusDot tone="danger" />
                <div>
                  <p className="text-sm font-medium text-danger">
                    Couldn&apos;t reach the telemetry endpoint
                  </p>
                  <p className="mt-1 text-2xs text-foreground-muted">
                    {error.message}
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Metric grid */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <MetricTile
              label="Queries · total"
              value={stats ? formatNumber(stats.metrics.queries_total) : "—"}
              icon={Database}
              loading={loading}
            />
            <MetricTile
              label="Queries · 24h"
              value={stats ? formatNumber(stats.metrics.queries_24h) : "—"}
              icon={Activity}
              loading={loading}
            />
            <MetricTile
              label="Queries · 7d"
              value={stats ? formatNumber(stats.metrics.queries_7d) : "—"}
              icon={Clock}
              loading={loading}
            />
            <MetricTile
              label="Indexed chunks"
              value={stats ? formatNumber(stats.metrics.indexed_chunks) : "—"}
              icon={Database}
              loading={loading}
            />
            <MetricTile
              label="p50 latency"
              value={
                stats ? formatDuration(stats.metrics.p50_latency_ms) : "—"
              }
              icon={Gauge}
              loading={loading}
            />
            <MetricTile
              label="p95 latency"
              value={
                stats ? formatDuration(stats.metrics.p95_latency_ms) : "—"
              }
              icon={Hourglass}
              loading={loading}
            />
            <MetricTile
              label="Avg retrieval"
              value={
                stats
                  ? `${stats.metrics.avg_retrieval_size} chunks`
                  : "—"
              }
              icon={Database}
              loading={loading}
            />
            <MetricTile
              label="Last active"
              value={stats ? formatRelative(stats.last_active_at) : "—"}
              icon={CheckCircle2}
              loading={loading}
            />
          </div>

          {/* Tabbed details */}
          <Card>
            <CardContent className="p-5">
              <Tabs value={tab} onValueChange={setTab}>
                <TabsList>
                  <TabsTrigger value="overview">Overview</TabsTrigger>
                  <TabsTrigger value="contract">Contract</TabsTrigger>
                  <TabsTrigger value="raw">Raw response</TabsTrigger>
                </TabsList>

                <TabsContent value="overview">
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                    <DetailRow
                      label="System slug"
                      value={stats?.system ?? "—"}
                      mono
                    />
                    <DetailRow label="Mode" value={stats?.mode ?? "live"} />
                    <DetailRow
                      label="Schema version"
                      value={`v${stats?.schema_version ?? 1}`}
                    />
                    <DetailRow
                      label="Status"
                      value={stats?.status ?? "—"}
                      tone={stats?.status === "operational" ? "success" : "warning"}
                    />
                    <DetailRow
                      label="Last deployed"
                      value={formatDate(stats?.last_deployed_at)}
                      hint={stats?.last_deployed_at ?? undefined}
                    />
                    <DetailRow
                      label="Last active"
                      value={formatDate(stats?.last_active_at)}
                      hint={stats?.last_active_at ?? undefined}
                    />
                    <DetailRow
                      label="Generated at"
                      value={formatDate(stats?.generated_at)}
                      hint={stats?.generated_at}
                    />
                    <DetailRow
                      label="Polling interval"
                      value={`${POLL_INTERVAL_MS / 1000}s`}
                      hint="visibility-aware"
                    />
                  </div>
                </TabsContent>

                <TabsContent value="contract">
                  <div className="space-y-3 text-sm text-foreground-muted">
                    <p>
                      This endpoint conforms to the public Tier-A telemetry
                      contract documented at{" "}
                      <a
                        className="text-brand underline-offset-2 hover:underline"
                        href="https://github.com/IgnazioDS/IgnazioDS/blob/main/TELEMETRY_SCHEMA.md"
                        target="_blank"
                        rel="noreferrer"
                      >
                        TELEMETRY_SCHEMA.md
                      </a>
                      .
                    </p>
                    <p>
                      Counters are sourced from the{" "}
                      <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-xs">
                        query_log
                      </code>{" "}
                      table populated by a fire-and-forget middleware on every{" "}
                      <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-xs">
                        /v1/run
                      </code>{" "}
                      request. Aggregations run on read with windowed{" "}
                      <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-xs">
                        percentile_cont
                      </code>{" "}
                      over the trailing 24h. The endpoint never returns 5xx —
                      DB outages degrade to{" "}
                      <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-xs">
                        status: &quot;degraded&quot;
                      </code>{" "}
                      with zeroed metrics and a contract-valid envelope.
                    </p>
                    <CodeBlock language="bash">
                      {`curl -i https://nexusrag-lyart.vercel.app/api/stats`}
                    </CodeBlock>
                  </div>
                </TabsContent>

                <TabsContent value="raw">
                  <CodeBlock language="json">
                    {stats
                      ? JSON.stringify(stats, null, 2)
                      : "Loading current response…"}
                  </CodeBlock>
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function MetricTile({
  label,
  value,
  icon: Icon,
  loading,
}: {
  label: string;
  value: string;
  icon: typeof Database;
  loading: boolean;
}) {
  return (
    <Card>
      <div className="p-4">
        <div className="flex items-start justify-between">
          <p className="text-2xs font-medium uppercase tracking-wider text-foreground-faint">
            {label}
          </p>
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-surface-2 text-foreground-muted">
            <Icon className="h-3.5 w-3.5" strokeWidth={1.75} />
          </div>
        </div>
        {loading ? (
          <Skeleton className="mt-2 h-7 w-24" />
        ) : (
          <p className="mt-2 text-2xl font-semibold tabular-nums text-foreground">
            {value}
          </p>
        )}
      </div>
    </Card>
  );
}

function DetailRow({
  label,
  value,
  hint,
  mono,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  mono?: boolean;
  tone?: "success" | "warning" | "danger";
}) {
  return (
    <div className="flex flex-col rounded-md border border-border-subtle bg-surface-2 px-3 py-2">
      <p className="text-2xs uppercase tracking-wider text-foreground-faint">
        {label}
      </p>
      <p
        className={`mt-1 text-sm font-medium ${
          mono ? "font-mono text-foreground-muted" : "text-foreground"
        } ${
          tone === "success"
            ? "text-success"
            : tone === "warning"
            ? "text-warning"
            : tone === "danger"
            ? "text-danger"
            : ""
        }`}
      >
        {value}
      </p>
      {hint && (
        <p className="mt-0.5 text-2xs text-foreground-subtle truncate">
          {hint}
        </p>
      )}
    </div>
  );
}
