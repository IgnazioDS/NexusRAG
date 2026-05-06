import { Badge } from "@/components/ui/badge";
import { StatusDot } from "@/components/ui/status-dot";

const STATUS_TONE: Record<
  string,
  { tone: "success" | "warning" | "danger" | "info" | "muted"; pulse?: boolean; badge: "success" | "warning" | "danger" | "info" | "muted" }
> = {
  succeeded: { tone: "success", badge: "success" },
  processing: { tone: "info", pulse: true, badge: "info" },
  queued: { tone: "warning", badge: "warning" },
  failed: { tone: "danger", badge: "danger" },
  pending: { tone: "muted", badge: "muted" },
};

const DEFAULT = { tone: "muted", badge: "muted" } as const;

/**
 * StatusBadge — pill with colored dot + label for document processing states.
 * The "processing" tone pulses to convey live activity.
 */
export function StatusBadge({ status }: { status: string }) {
  const config = STATUS_TONE[status.toLowerCase()] ?? DEFAULT;
  return (
    <Badge variant={config.badge} className="capitalize">
      <StatusDot tone={config.tone} size="sm" pulse={config.pulse} />
      {status}
    </Badge>
  );
}
