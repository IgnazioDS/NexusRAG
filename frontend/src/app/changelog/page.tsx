import { Github, GitBranch, Sparkles, Tag } from "lucide-react";
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
import { RELEASES, RELEASE_TOTAL, type Era } from "@/lib/changelog";
import { PROJECT } from "@/lib/project";

export const metadata = { title: "Changelog" };

const ERA_TONE: Record<Era, "warning" | "info" | "muted" | "success" | "brand"> = {
  Unreleased: "warning",
  "Notification reliability": "info",
  "Compliance + cost + SLA": "info",
  "Identity + ABAC": "info",
  "Resilience + crypto": "muted",
  "Reliability + DR": "muted",
  "Enterprise primitives": "muted",
  Foundation: "muted",
};

interface EraSummary {
  era: Era;
  blurb: string;
}

const ERA_SUMMARIES: EraSummary[] = [
  {
    era: "Unreleased",
    blurb:
      "Active hardening of the notification receiver contract — typed headers, deterministic dedupe, signature parsing.",
  },
  {
    era: "Notification reliability",
    blurb:
      "End-to-end notification reliability — destinations, routing policies, ARQ delivery, DLQ persistence + replay, signature contracts.",
  },
  {
    era: "Compliance + cost + SLA",
    blurb:
      "SOC 2 control catalog snapshots, evidence bundles, perf harness, SLA engine, cost metering, alert + incident automation.",
  },
  {
    era: "Identity + ABAC",
    blurb:
      "Enterprise SSO (OIDC) + SCIM 2.0, ABAC policy engine with simulation, document ACLs with creator-owner default.",
  },
  {
    era: "Resilience + crypto",
    blurb:
      "Envelope encryption with KMS rotation, governance + DSAR + retention pipeline, multi-region failover control plane.",
  },
  {
    era: "Reliability + DR",
    blurb:
      "Reliability primitives (retries, breakers, bulkheads), kill switches, DR backups with signed manifests, BFF SSE protocol.",
  },
  {
    era: "Enterprise primitives",
    blurb:
      "/v1 versioned API + envelopes + idempotency keys, plan entitlements, tenant self-serve, quotas + 402 contract.",
  },
  {
    era: "Foundation",
    blurb:
      "Streaming agent + SSE framing, multi-cloud retrieval routing, async ingestion, audit log, RBAC, rate limiting.",
  },
];

export default function ChangelogPage() {
  // Group releases by era preserving the order in RELEASES (newest first).
  const byEra = new Map<Era, typeof RELEASES>();
  for (const r of RELEASES) {
    const arr = byEra.get(r.era) ?? [];
    arr.push(r);
    byEra.set(r.era, arr);
  }

  return (
    <>
      <TopBar
        title="Changelog"
        description={`${RELEASE_TOTAL} tagged releases across ${
          byEra.size
        } eras`}
        actions={
          <Button asChild size="sm" variant="outline">
            <a
              href={`${PROJECT.github_url}/blob/main/CHANGELOG.md`}
              target="_blank"
              rel="noreferrer"
            >
              <Github />
              Source
            </a>
          </Button>
        }
      />
      <div className="dot-grid grid-fade flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-4xl space-y-5 p-6">
          {/* Pitch */}
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-1.5 mb-2">
                <Badge variant="success">{RELEASE_TOTAL} releases</Badge>
                <Badge variant="outline">{byEra.size} eras</Badge>
                <Badge variant="outline">CHANGELOG.md</Badge>
              </div>
              <CardTitle className="text-xl">
                Releases tell the story.
              </CardTitle>
              <CardDescription className="leading-relaxed">
                Each release is grouped into a thematic era so the timeline
                reads as a narrative arc — from the foundational streaming
                agent through enterprise primitives, identity + ABAC,
                compliance, cost + SLA, resilience, and the current focus on
                notification reliability.
              </CardDescription>
            </CardHeader>
          </Card>

          {/* Eras + releases */}
          {ERA_SUMMARIES.map((eraSummary) => {
            const releases = byEra.get(eraSummary.era);
            if (!releases || releases.length === 0) return null;
            return (
              <section key={eraSummary.era} className="space-y-3">
                <div className="flex items-baseline justify-between gap-3">
                  <div>
                    <h2 className="text-md font-semibold tracking-tight text-foreground">
                      {eraSummary.era}
                    </h2>
                    <p className="mt-0.5 text-2xs text-foreground-muted leading-relaxed">
                      {eraSummary.blurb}
                    </p>
                  </div>
                  <span className="text-2xs font-mono text-foreground-faint shrink-0">
                    {releases.length}{" "}
                    {releases.length === 1 ? "release" : "releases"}
                  </span>
                </div>
                <div className="relative space-y-2.5">
                  {releases.map((r) => (
                    <Card key={r.version}>
                      <CardHeader className="pb-2.5">
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex items-center gap-2 min-w-0">
                            {r.version === "Unreleased" ? (
                              <GitBranch className="h-3.5 w-3.5 shrink-0 text-warning" />
                            ) : (
                              <Tag className="h-3.5 w-3.5 shrink-0 text-brand" />
                            )}
                            <CardTitle className="text-md font-mono truncate">
                              {r.version}
                            </CardTitle>
                            {r.date && (
                              <span className="text-2xs font-mono text-foreground-faint shrink-0">
                                {r.date}
                              </span>
                            )}
                          </div>
                          <Badge variant={ERA_TONE[r.era]}>{r.era}</Badge>
                        </div>
                        <CardDescription className="mt-1.5 leading-relaxed">
                          {r.theme}
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <ul className="space-y-1">
                          {r.highlights.map((h, i) => (
                            <li
                              key={i}
                              className="flex items-start gap-2 text-xs text-foreground-muted leading-relaxed"
                            >
                              <Sparkles className="mt-0.5 h-3 w-3 shrink-0 text-foreground-faint" />
                              {h}
                            </li>
                          ))}
                        </ul>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </>
  );
}
