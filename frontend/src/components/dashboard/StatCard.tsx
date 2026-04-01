import { Skeleton } from "@/components/ui/skeleton";
import { Sparkline } from "@/components/ui/sparkline";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  title: string;
  value: string;
  subtitle?: string;
  icon: LucideIcon;
  trend?: "up" | "down" | "neutral";
  sparkData?: number[];
  loading?: boolean;
  color?: "indigo" | "emerald" | "amber";
}

const COLOR_MAP = {
  indigo: {
    iconBg: "bg-indigo-500/10",
    iconText: "text-indigo-400",
    sparkColor: "#6366f1",
    delta: "text-indigo-400",
  },
  emerald: {
    iconBg: "bg-emerald-500/10",
    iconText: "text-emerald-400",
    sparkColor: "#10b981",
    delta: "text-emerald-400",
  },
  amber: {
    iconBg: "bg-amber-500/10",
    iconText: "text-amber-400",
    sparkColor: "#f59e0b",
    delta: "text-amber-400",
  },
};

export function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  sparkData,
  loading,
  color = "indigo",
}: StatCardProps) {
  const c = COLOR_MAP[color];

  if (loading) {
    return (
      <div className="glow-card stat-card-accent rounded-xl p-5">
        <div className="flex items-start justify-between mb-4">
          <Skeleton className="h-3.5 w-28" />
          <Skeleton className="h-8 w-8 rounded-lg" />
        </div>
        <Skeleton className="h-8 w-20 mb-2" />
        <Skeleton className="h-3 w-32" />
      </div>
    );
  }

  return (
    <div className="glow-card stat-card-accent rounded-xl p-5 group hover:border-indigo-500/20 transition-colors">
      <div className="flex items-start justify-between">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-600">{title}</p>
        <div className={cn("flex h-8 w-8 items-center justify-center rounded-lg", c.iconBg)}>
          <Icon className={cn("h-4 w-4", c.iconText)} strokeWidth={1.75} />
        </div>
      </div>

      <div className="mt-3 flex items-end justify-between">
        <div>
          <p className="count-in text-3xl font-bold tracking-tight text-zinc-100 tabular-nums">
            {value}
          </p>
          {subtitle && (
            <p className="mt-1 text-[11px] text-zinc-600 leading-tight">{subtitle}</p>
          )}
        </div>
        {sparkData && sparkData.length > 1 && (
          <div className="opacity-70 group-hover:opacity-100 transition-opacity">
            <Sparkline data={sparkData} color={c.sparkColor} width={72} height={28} />
          </div>
        )}
      </div>
    </div>
  );
}
