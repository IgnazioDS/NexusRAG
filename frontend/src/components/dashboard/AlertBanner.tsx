import { AlertTriangle, Info, XCircle } from "lucide-react";
import type { DashboardAlert } from "@/lib/api";

const SEVERITY_STYLES: Record<string, {
  bg: string; border: string; text: string; bar: string; icon: typeof Info;
}> = {
  critical: { bg: "bg-red-500/[0.07]", border: "border-red-500/20", text: "text-red-400", bar: "bg-red-500", icon: XCircle },
  high:     { bg: "bg-red-500/[0.07]", border: "border-red-500/20", text: "text-red-400", bar: "bg-red-500", icon: XCircle },
  warning:  { bg: "bg-amber-500/[0.07]", border: "border-amber-500/20", text: "text-amber-400", bar: "bg-amber-500", icon: AlertTriangle },
  info:     { bg: "bg-indigo-500/[0.07]", border: "border-indigo-500/20", text: "text-indigo-400", bar: "bg-indigo-500", icon: Info },
};

function getStyle(severity: string) {
  return SEVERITY_STYLES[severity.toLowerCase()] ?? SEVERITY_STYLES.info;
}

export function AlertBanner({ alerts }: { alerts: DashboardAlert[] }) {
  if (!alerts.length) return null;

  return (
    <div className="space-y-2">
      {alerts.map((alert) => {
        const { bg, border, text, bar, icon: Icon } = getStyle(alert.severity);
        return (
          <div
            key={alert.id}
            className={`relative flex items-start gap-3 overflow-hidden rounded-xl border ${border} ${bg} px-4 py-3`}
          >
            {/* Left accent bar */}
            <div className={`absolute left-0 top-0 h-full w-[3px] ${bar} opacity-60 rounded-r`} />
            <Icon className={`mt-0.5 ml-1 h-3.5 w-3.5 shrink-0 ${text}`} />
            <div>
              <p className={`text-[13px] font-medium leading-snug ${text}`}>{alert.message}</p>
              <p className="mt-0.5 text-[10px] uppercase tracking-wide text-zinc-700">{alert.severity}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
