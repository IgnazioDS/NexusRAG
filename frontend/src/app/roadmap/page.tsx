import { Activity, Compass, Github, Map as MapIcon, Rocket } from "lucide-react";
import { TopBar } from "@/components/layout/TopBar";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PROJECT } from "@/lib/project";

export const metadata = { title: "Roadmap" };

interface Phase {
  label: string;
  status: "now" | "next" | "later";
  description: string;
  items: string[];
}

/**
 * NexusRAG roadmap reflects production status, not the showcase ramp-up.
 * "Now" = what's live and being maintained; "Next" = themes from the
 * Unreleased CHANGELOG section + active hardening work; "Later" = vision
 * items the platform is positioned to enable.
 */
const PHASES: Phase[] = [
  {
    label: "Now — Live in production",
    status: "now",
    description:
      "The platform serves real workload through a streaming LangGraph agent. Tier-A telemetry exposes workload counters, latency percentiles, and uptime. Audit log is tamper-evident and always on.",
    items: [
      "Multi-tenant /v1/run streaming endpoint with SSE",
      "RBAC + ABAC + document ACLs (default-deny)",
      "Bedrock KB and Vertex AI Search retrieval routing live",
      "Envelope encryption + KMS key rotation enforced",
      "SOC 2 evidence bundles persisted under var/evidence",
      "Public Tier-A /api/stats with workload metrics",
    ],
  },
  {
    label: "Next — Reliability + governance hardening",
    status: "next",
    description:
      "Active themes from the CHANGELOG Unreleased section: notification receiver contract v1.0, governance retention proofs, and compliance evidence automation. These tighten the operational surface without changing the public contract.",
    items: [
      "Notification Receiver Contract v1.0 (typed headers, signature parsing, dedupe)",
      "DSAR / governance retention-proof workflows",
      "Tenant-scoped notification routing with DLQ replay",
      "Admin API key lifecycle endpoints + keyring rotation tooling",
      "Operability evaluator worker with distributed locking",
    ],
  },
  {
    label: "Later — Federated + edge-native retrieval",
    status: "later",
    description:
      "Where the platform is heading once the current reliability themes close. The architecture (multi-cloud retrieval routing, audit-evident logs, kill-switched feature flags) is already shaped for these.",
    items: [
      "Federated retrieval across customer-owned data planes",
      "Active failover with geo-replicated audit log",
      "Self-serve compliance attestation export",
      "Edge-cached embeddings with regional TTLs",
      "Customer-supplied LLM provider plug-in surface",
    ],
  },
];

const TONE: Record<Phase["status"], "success" | "info" | "muted"> = {
  now: "success",
  next: "info",
  later: "muted",
};

export default function RoadmapPage() {
  return (
    <>
      <TopBar
        title="Roadmap"
        description={`Stage and direction for ${PROJECT.name}`}
        actions={
          <Button asChild size="sm" variant="outline">
            <a href={PROJECT.github_url} target="_blank" rel="noreferrer">
              <Github />
              GitHub
            </a>
          </Button>
        }
      />
      <div className="flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-4xl space-y-5 p-6">
          {/* Stage card */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <Compass className="h-3.5 w-3.5 text-brand" />
                  Current stage
                </CardTitle>
                <CardDescription className="mt-1">
                  Where this project sits today.
                </CardDescription>
              </div>
              <Badge variant="success" className="!text-xs">
                {PROJECT.stage}
              </Badge>
            </CardHeader>
          </Card>

          {/* Phases */}
          <div className="relative space-y-4">
            {PHASES.map((phase, i) => (
              <div key={phase.label} className="relative">
                {i < PHASES.length - 1 && (
                  <div
                    aria-hidden
                    className="absolute left-[14px] top-12 w-px h-[calc(100%+1rem-2.5rem)] bg-border-subtle"
                  />
                )}
                <div className="flex gap-3">
                  <div className="flex shrink-0 flex-col items-center">
                    <div
                      className={`flex h-7 w-7 items-center justify-center rounded-full border ${
                        phase.status === "now"
                          ? "border-success/40 bg-success/15 text-success"
                          : phase.status === "next"
                          ? "border-info/30 bg-info/10 text-info"
                          : "border-border bg-surface-2 text-foreground-faint"
                      }`}
                    >
                      {phase.status === "now" ? (
                        <Activity className="h-3.5 w-3.5" />
                      ) : phase.status === "next" ? (
                        <Rocket className="h-3.5 w-3.5" />
                      ) : (
                        <MapIcon className="h-3.5 w-3.5" />
                      )}
                    </div>
                  </div>
                  <Card className="flex-1">
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-md">{phase.label}</CardTitle>
                        <Badge variant={TONE[phase.status]}>
                          {phase.status}
                        </Badge>
                      </div>
                      <CardDescription className="mt-1 leading-relaxed">
                        {phase.description}
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <ul className="space-y-2">
                        {phase.items.map((item, idx) => (
                          <li
                            key={idx}
                            className="flex items-start gap-2.5 text-sm text-foreground-muted"
                          >
                            <span className="mt-1.5 inline-flex h-1 w-1 shrink-0 rounded-full bg-foreground-faint" />
                            {item}
                          </li>
                        ))}
                      </ul>
                    </CardContent>
                  </Card>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
