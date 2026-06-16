import {
  BookOpenCheck,
  FileLock2,
  History,
  Key,
  Scale,
  Shield,
  ShieldCheck,
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

export const metadata = { title: "Compliance & Trust" };

interface ControlDomain {
  label: string;
  description: string;
  api?: string;
  flag?: string;
  /** "shipped" — implemented and persisting evidence; "ongoing" — continuous evaluation. */
  status: "shipped" | "ongoing";
  bullets: string[];
}

const DOMAINS: ControlDomain[] = [
  {
    label: "SOC 2 control catalog",
    description:
      "Continuous evaluation engine over a SOC 2 control catalog. Snapshots persist evidence under var/evidence with signed bundles.",
    api: "POST /v1/admin/compliance/snapshots",
    flag: "COMPLIANCE_ENABLED",
    status: "ongoing",
    bullets: [
      "Continuous evaluation engine",
      "Signed evidence bundles with verification",
      "Persisted artifact paths in artifact_paths_json",
      "Compliance ops posture endpoint + scheduling tasks",
    ],
  },
  {
    label: "Audit log",
    description:
      "Tamper-evident audit log persisted in audit_events. Auth, security, and data mutation events recorded with metadata redaction.",
    flag: "always on",
    status: "shipped",
    bullets: [
      "Central audit service across the API surface",
      "Admin-only audit query endpoints (tenant-scoped)",
      "Metadata redaction policy for sensitive fields",
      "Retention proof workflows + 24h ops summaries",
    ],
  },
  {
    label: "DSAR + data governance",
    description:
      "Data subject access requests with auditable lifecycle. Retention pipeline supports legal hold supersession and anonymize/hard-delete.",
    api: "POST /v1/admin/governance/retention/run",
    flag: "GOVERNANCE_POLICY_ENGINE_ENABLED",
    status: "shipped",
    bullets: [
      "Export, delete, anonymize APIs with artifact generation",
      "Retention runs persisted with proof exports",
      "Legal hold supersession on the retention pipeline",
      "Policy-as-code engine for deterministic rule evaluation",
    ],
  },
  {
    label: "Envelope encryption",
    description:
      "AES-256-GCM with pluggable KMS providers. Tenant key registry + encrypted blob store. Resumable re-encryption jobs with telemetry.",
    api: "/v1/admin/keyring",
    flag: "CRYPTO_ENABLED + CRYPTO_PROVIDER",
    status: "shipped",
    bullets: [
      "Pluggable KMS providers with crypto error contracts",
      "Key rotation APIs with resumable jobs",
      "KEYRING_MASTER_KEY_REQUIRED required-only mode",
      "Crypto posture surfaced in governance status",
    ],
  },
  {
    label: "API key lifecycle",
    description:
      "Hashed key storage; admin lifecycle endpoints (expiration / reactivation / revocation). Inactive key denial with deterministic codes.",
    api: "/v1/admin/api-keys",
    flag: "AUTH_ENABLED",
    status: "shipped",
    bullets: [
      "Optional per-key expiration + expiry enforcement",
      "Inactivity reporting with admin reactivation",
      "Rotation helper script + auditable lifecycle events",
      "AUTH_INACTIVE_KEY denial path in the auth pipeline",
    ],
  },
  {
    label: "DR backup + restore",
    description:
      "DR backup tooling with signed manifests; readiness/backups/restore-drill ops endpoints. Encrypted + signed backups with retention pruning.",
    flag: "BACKUP_ENABLED",
    status: "shipped",
    bullets: [
      "Signed backup manifests + drill reporting",
      "Backup retention pruning",
      "Restore-drill checklist runbook",
      "Multi-region failover control plane (FAILOVER_ENABLED)",
    ],
  },
];

const RUNBOOKS = [
  "soc2-audit-prep.md",
  "evidence-bundles.md",
  "evidence-bundle-verification.md",
  "compliance-control-failure-response.md",
  "compliance-scheduling-and-retention.md",
  "compliance-snapshot.md",
  "audit-evidence-export.md",
  "retention-and-anonymization.md",
  "retention-proof.md",
  "dsar-handling.md",
  "key-rotation.md",
  "key-rotation-execution.md",
  "key-rotation-for-backups.md",
  "key-compromise-response.md",
  "kms-outage-procedure.md",
  "encrypted-artifact-access.md",
  "legal-hold-procedure.md",
  "dr-backup-restore.md",
  "restore-drill-checklist.md",
  "failover-execution.md",
  "failover-rollback.md",
];

const STATUS_TONE = {
  shipped: { variant: "success" as const, label: "shipped" },
  ongoing: { variant: "info" as const, label: "ongoing" },
};

export default function CompliancePage() {
  return (
    <>
      <TopBar
        title="Compliance & Trust"
        description="SOC 2 posture, audit trail, governance, and the runbooks that operate them"
      />
      <div className="dot-grid grid-fade flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-5xl space-y-6 p-6">
          {/* Posture summary */}
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-1.5 mb-2">
                <Badge variant="success">
                  <ShieldCheck className="h-3 w-3" />
                  SOC 2 Ready
                </Badge>
                <Badge variant="outline">Tamper-evident audit</Badge>
                <Badge variant="outline">Envelope-encrypted</Badge>
              </div>
              <CardTitle className="text-xl">
                Continuous evaluation. Signed evidence. Auditable lifecycle.
              </CardTitle>
              <CardDescription className="leading-relaxed">
                NexusRAG ships compliance as automation rather than as
                paperwork. A SOC 2 control catalog runs in continuous
                evaluation, evidence bundles are persisted and signed, and
                every privileged action lands in a tamper-evident audit
                log. The runbook library below is the operational counterpart —
                each procedure is exercised in CI, not stashed in a wiki.
              </CardDescription>
            </CardHeader>
          </Card>

          {/* Control domains */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {DOMAINS.map((d) => {
              const tone = STATUS_TONE[d.status];
              return (
                <Card key={d.label}>
                  <CardHeader>
                    <div className="flex items-center justify-between gap-2">
                      <CardTitle className="flex items-center gap-2 text-sm">
                        <Shield className="h-3.5 w-3.5 text-brand" />
                        {d.label}
                      </CardTitle>
                      <Badge variant={tone.variant}>{tone.label}</Badge>
                    </div>
                    <CardDescription className="mt-1.5 leading-relaxed">
                      {d.description}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-1.5">
                      {d.bullets.map((b, i) => (
                        <li
                          key={i}
                          className="flex items-start gap-2 text-xs text-foreground-muted leading-relaxed"
                        >
                          <span className="mt-1.5 inline-flex h-1 w-1 shrink-0 rounded-full bg-foreground-faint" />
                          {b}
                        </li>
                      ))}
                    </ul>
                    {(d.api || d.flag) && (
                      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border-subtle pt-2.5">
                        {d.api && (
                          <span className="inline-flex items-center gap-1 text-2xs font-mono text-foreground-faint">
                            <FileLock2 className="h-3 w-3" />
                            {d.api}
                          </span>
                        )}
                        {d.flag && (
                          <span className="inline-flex items-center gap-1 text-2xs font-mono text-foreground-faint">
                            <Key className="h-3 w-3" />
                            {d.flag}
                          </span>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* Authorization layer summary */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Scale className="h-3.5 w-3.5 text-brand" />
                Authorization model
              </CardTitle>
              <CardDescription>
                RBAC + ABAC + document ACLs with default-deny. See{" "}
                <a
                  href="/architecture#edge"
                  className="underline-offset-2 hover:underline text-foreground"
                >
                  the architecture page
                </a>{" "}
                for the full request authorization pipeline.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                <div className="rounded-md border border-border-subtle bg-surface-2 p-3">
                  <p className="text-2xs font-medium uppercase tracking-wider text-foreground-faint">
                    RBAC
                  </p>
                  <p className="mt-1 text-sm font-semibold text-foreground">
                    reader / editor / admin
                  </p>
                  <p className="mt-1 text-2xs text-foreground-muted leading-relaxed">
                    Endpoint-level role matrix; tenant-bound principals.
                  </p>
                </div>
                <div className="rounded-md border border-border-subtle bg-surface-2 p-3">
                  <p className="text-2xs font-medium uppercase tracking-wider text-foreground-faint">
                    ABAC
                  </p>
                  <p className="mt-1 text-sm font-semibold text-foreground">
                    deny-first / allow-then
                  </p>
                  <p className="mt-1 text-2xs text-foreground-muted leading-relaxed">
                    Priority-aware DSL with simulation API.
                  </p>
                </div>
                <div className="rounded-md border border-border-subtle bg-surface-2 p-3">
                  <p className="text-2xs font-medium uppercase tracking-wider text-foreground-faint">
                    Doc ACL
                  </p>
                  <p className="mt-1 text-sm font-semibold text-foreground">
                    creator-owner default
                  </p>
                  <p className="mt-1 text-2xs text-foreground-muted leading-relaxed">
                    Expiring grants ignored; AUTHZ_DEFAULT_DENY in prod.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Runbooks */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <BookOpenCheck className="h-3.5 w-3.5 text-brand" />
                Operational runbooks
              </CardTitle>
              <CardDescription>
                {RUNBOOKS.length} compliance + crypto + DR runbooks live in{" "}
                <code className="font-mono text-foreground">
                  docs/runbooks/
                </code>
                . Every procedure has a deterministic execution path; most are
                exercised in CI.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1.5">
                {RUNBOOKS.map((r) => (
                  <span
                    key={r}
                    className="inline-flex items-center rounded-md border border-border-subtle bg-surface-2 px-2 py-0.5 text-2xs font-mono text-foreground-muted"
                  >
                    {r}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* History pointer */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <History className="h-3.5 w-3.5 text-brand" />
                Trace the journey
              </CardTitle>
              <CardDescription>
                The compliance posture wasn&apos;t bolted on. Audit log shipped in{" "}
                <code className="font-mono text-foreground">0.8.0</code>;
                envelope encryption in{" "}
                <code className="font-mono text-foreground">1.9.0</code>; SOC 2
                catalog in{" "}
                <code className="font-mono text-foreground">2.0.0</code>; ABAC
                in{" "}
                <code className="font-mono text-foreground">2.2.0</code>. See
                the{" "}
                <a
                  href="/changelog"
                  className="underline-offset-2 hover:underline text-foreground"
                >
                  release timeline
                </a>{" "}
                for the full trajectory.
              </CardDescription>
            </CardHeader>
          </Card>
        </div>
      </div>
    </>
  );
}
