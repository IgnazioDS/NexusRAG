import {
  Boxes,
  ChevronRight,
  Database,
  Layers,
  Lock,
  Network,
  Workflow,
} from "lucide-react";
import { TopBar } from "@/components/layout/TopBar";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LAYERS, AUTHZ_PIPELINE } from "@/lib/architecture";

export const metadata = { title: "Architecture" };

const LAYER_ICONS: Record<string, typeof Layers> = {
  edge: Lock,
  agent: Workflow,
  retrieval: Network,
  infra: Database,
};

export default function ArchitecturePage() {
  return (
    <>
      <TopBar
        title="Architecture"
        description="Layered request flow, agent runtime, retrieval backends, and shared infrastructure"
      />
      <div className="dot-grid grid-fade flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-5xl space-y-6 p-6">
          {/* Pitch */}
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-1.5 mb-2">
                <Badge variant="success">Live in production</Badge>
                <Badge variant="outline">Multi-tenant</Badge>
                <Badge variant="outline">Multi-cloud</Badge>
              </div>
              <CardTitle className="text-xl">
                One streaming endpoint. Layered enforcement. Pluggable retrieval.
              </CardTitle>
              <CardDescription className="leading-relaxed">
                Every request to <code className="font-mono text-foreground">/v1/run</code>{" "}
                passes through five enforcement layers before any retrieval or
                generation work happens. The agent runtime then routes retrieval
                across pgvector, Bedrock KB, or Vertex AI Search — picked
                per-corpus from a single config field. Stateful infrastructure
                (Postgres, Redis, ARQ workers) is shared across the platform
                with envelope-encrypted secrets and a tamper-evident audit log.
              </CardDescription>
            </CardHeader>
          </Card>

          {/* Authorization pipeline */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Lock className="h-3.5 w-3.5 text-brand" />
                Request authorization pipeline
              </CardTitle>
              <CardDescription>
                Six-step decision order for every document action. Order is
                non-negotiable: tenant boundary first, default-deny last.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ol className="space-y-2.5">
                {AUTHZ_PIPELINE.map((step, i) => (
                  <li
                    key={step.step}
                    className="flex items-start gap-3 rounded-md border border-border-subtle bg-surface-2 px-3 py-2.5"
                  >
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand/15 text-2xs font-semibold text-brand tabular-nums">
                      {step.step}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-semibold text-foreground">
                        {step.label}
                      </p>
                      <p className="mt-0.5 text-sm text-foreground-muted leading-relaxed">
                        {step.detail}
                      </p>
                      <p className="mt-1 text-2xs text-foreground-faint font-mono">
                        ↳ {step.failure}
                      </p>
                    </div>
                    {i < AUTHZ_PIPELINE.length - 1 && (
                      <ChevronRight className="mt-1 h-3.5 w-3.5 shrink-0 text-foreground-faint" />
                    )}
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>

          {/* Layered architecture */}
          {LAYERS.map((layer) => {
            const Icon = LAYER_ICONS[layer.id] ?? Boxes;
            return (
              <Card key={layer.id} id={layer.id}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Icon className="h-3.5 w-3.5 text-brand" />
                    {layer.label}
                  </CardTitle>
                  <CardDescription className="leading-relaxed">
                    {layer.description}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-1 gap-2.5 md:grid-cols-2 lg:grid-cols-3">
                    {layer.components.map((c) => (
                      <div
                        key={c.id}
                        className="rounded-md border border-border-subtle bg-surface-2 p-3"
                      >
                        <div className="flex items-baseline justify-between gap-2">
                          <p className="text-sm font-semibold text-foreground">
                            {c.label}
                          </p>
                          <span className="text-2xs font-mono text-foreground-faint shrink-0">
                            {c.subLabel}
                          </span>
                        </div>
                        <p className="mt-1.5 text-xs text-foreground-muted leading-relaxed">
                          {c.description}
                        </p>
                        {c.bullets && c.bullets.length > 0 && (
                          <ul className="mt-2 space-y-1">
                            {c.bullets.map((b, i) => (
                              <li
                                key={i}
                                className="flex items-start gap-1.5 text-2xs text-foreground-faint"
                              >
                                <span className="mt-1 inline-flex h-1 w-1 shrink-0 rounded-full bg-foreground-faint" />
                                <span className="font-mono leading-relaxed">
                                  {b}
                                </span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </>
  );
}
