"use client";
import { useEffect, useState } from "react";
import { FileText, Activity, Gauge } from "lucide-react";
import {
  fetchBootstrap, fetchDashboard, fetchActivity,
  type BootstrapData, type DashboardData, type ActivityItem,
} from "@/lib/api";
import { TopBar } from "@/components/layout/TopBar";
import { StatCard } from "@/components/dashboard/StatCard";
import { QuotaBar } from "@/components/dashboard/QuotaBar";
import { AlertBanner } from "@/components/dashboard/AlertBanner";
import { ActivityFeed } from "@/components/dashboard/ActivityFeed";

// Placeholder sparkline data until real trend data is available from the BFF
const DOC_SPARK = [12, 18, 15, 22, 28, 24, 31, 38, 35, 42];
const REQ_SPARK = [40, 55, 48, 62, 58, 70, 65, 80, 74, 88];
const QUOTA_SPARK = [10, 20, 18, 25, 30, 28, 35, 38, 42, 45];

export default function DashboardPage() {
  const [bootstrap, setBootstrap] = useState<BootstrapData | null>(null);
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([
      fetchBootstrap(),
      fetchDashboard(),
      fetchActivity({ limit: 10 }),
    ]).then(([bs, dash, act]) => {
      if (bs.status === "fulfilled") setBootstrap(bs.value);
      if (dash.status === "fulfilled") setDashboard(dash.value);
      if (act.status === "fulfilled") setActivity(act.value.items);
      setLoading(false);
    });
  }, []);

  const cardMap = Object.fromEntries((dashboard?.cards ?? []).map((c) => [c.id, c]));
  const docCard   = cardMap["total_documents"] ?? cardMap["documents"];
  const reqCard   = cardMap["requests_today"]  ?? cardMap["requests"];
  const quotaCard = cardMap["quota_used"]      ?? cardMap["quota"];

  return (
    <>
      <TopBar title="Overview" />
      <div className="dot-grid flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl space-y-5 p-6">
          {/* Alerts */}
          {dashboard?.alerts && dashboard.alerts.length > 0 && (
            <AlertBanner alerts={dashboard.alerts} />
          )}

          {/* Stat cards */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <StatCard
              title={docCard?.title ?? "Total Documents"}
              value={docCard?.value ?? "—"}
              subtitle={docCard?.subtitle}
              icon={FileText}
              color="indigo"
              sparkData={DOC_SPARK}
              loading={loading}
            />
            <StatCard
              title={reqCard?.title ?? "Requests Today"}
              value={reqCard?.value ?? "—"}
              subtitle={reqCard?.subtitle}
              icon={Activity}
              color="emerald"
              sparkData={REQ_SPARK}
              loading={loading}
            />
            <StatCard
              title={quotaCard?.title ?? "Quota Used"}
              value={quotaCard?.value ?? "—"}
              subtitle={quotaCard?.subtitle}
              icon={Gauge}
              color="amber"
              sparkData={QUOTA_SPARK}
              loading={loading}
            />
          </div>

          {/* Quota + Activity row */}
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
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
