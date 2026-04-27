import { AlertTriangle, Info, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { DashboardAlert } from "@/lib/api";

const SEVERITY_STYLES: Record<
  string,
  { wrapper: string; iconColor: string; icon: typeof Info }
> = {
  critical: {
    wrapper: "border-danger/30 bg-danger/5",
    iconColor: "text-danger",
    icon: XCircle,
  },
  high: {
    wrapper: "border-danger/30 bg-danger/5",
    iconColor: "text-danger",
    icon: XCircle,
  },
  warning: {
    wrapper: "border-warning/30 bg-warning/5",
    iconColor: "text-warning",
    icon: AlertTriangle,
  },
  info: {
    wrapper: "border-info/30 bg-info/5",
    iconColor: "text-info",
    icon: Info,
  },
};

function styleFor(severity: string) {
  return SEVERITY_STYLES[severity.toLowerCase()] ?? SEVERITY_STYLES.info;
}

export function AlertBanner({ alerts }: { alerts: DashboardAlert[] }) {
  if (!alerts.length) return null;
  return (
    <div className="space-y-2">
      {alerts.map((alert) => {
        const { wrapper, iconColor, icon: Icon } = styleFor(alert.severity);
        return (
          <div
            key={alert.id}
            className={cn(
              "flex items-start gap-3 rounded-lg border px-4 py-3",
              wrapper,
            )}
          >
            <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", iconColor)} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-foreground leading-snug">
                {alert.message}
              </p>
              <p className="mt-1 text-2xs uppercase tracking-wider text-foreground-faint">
                {alert.severity}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
}
