"use client";

import { useEffect, useState } from "react";
import { Eye, EyeOff, Key, Plus, ShieldCheck } from "lucide-react";
import { fetchBootstrap, type BootstrapData } from "@/lib/api";
import { TopBar } from "@/components/layout/TopBar";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { CodeBlock } from "@/components/ui/code-block";
import { EmptyState } from "@/components/ui/empty-state";

export default function ApiKeysPage() {
  const [bootstrap, setBootstrap] = useState<BootstrapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [reveal, setReveal] = useState(false);

  useEffect(() => {
    fetchBootstrap()
      .then((d) => setBootstrap(d))
      .catch(() => null)
      .finally(() => setLoading(false));
  }, []);

  // The principal endpoint exposes the active key id but not the secret.
  // For local-dev we read the env-injected key (NEXT_PUBLIC_API_KEY) so the
  // user can copy it for curl examples; in production this is empty.
  const liveKeyId = bootstrap?.principal.api_key_id ?? "—";
  const localKey =
    typeof window !== "undefined"
      ? process.env.NEXT_PUBLIC_API_KEY ?? ""
      : "";

  return (
    <>
      <TopBar
        title="API Keys"
        description="Authentication credentials for the NexusRAG BFF"
        actions={
          <Button size="sm" variant="primary" disabled>
            <Plus />
            New key
          </Button>
        }
      />
      <div className="flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-3xl space-y-5 p-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Key className="h-3.5 w-3.5 text-brand" />
                Active key
              </CardTitle>
              <CardDescription>
                The key your dashboard session is currently using.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {loading ? (
                <Skeleton className="h-10 w-full" />
              ) : (
                <>
                  <div className="space-y-1.5">
                    <label className="text-2xs font-medium uppercase tracking-wider text-foreground-faint">
                      Key ID
                    </label>
                    <Input
                      readOnly
                      value={liveKeyId}
                      className="font-mono"
                    />
                  </div>
                  {localKey && (
                    <div className="space-y-1.5">
                      <label className="text-2xs font-medium uppercase tracking-wider text-foreground-faint">
                        Local secret (env)
                      </label>
                      <div className="flex gap-2">
                        <Input
                          readOnly
                          type={reveal ? "text" : "password"}
                          value={localKey}
                          className="font-mono"
                        />
                        <Button
                          variant="secondary"
                          size="default"
                          onClick={() => setReveal((r) => !r)}
                        >
                          {reveal ? <EyeOff /> : <Eye />}
                          {reveal ? "Hide" : "Reveal"}
                        </Button>
                      </div>
                      <p className="text-2xs text-foreground-subtle">
                        Sourced from <code className="font-mono">NEXT_PUBLIC_API_KEY</code> at build time.
                        Production keys are managed via the Vercel project settings.
                      </p>
                    </div>
                  )}
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Badge variant="brand">
                      <ShieldCheck className="h-3 w-3" />
                      Bearer auth
                    </Badge>
                    <Badge variant="outline">RBAC scoped</Badge>
                    <Badge variant="outline">audit logged</Badge>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Using your key</CardTitle>
              <CardDescription>
                The BFF accepts a standard{" "}
                <code className="font-mono">Bearer</code> token on every
                versioned route.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <CodeBlock language="bash">
                {`curl https://nexusrag-lyart.vercel.app/v1/ui/bootstrap \\
  -H "Authorization: Bearer $NEXUSRAG_API_KEY"`}
              </CodeBlock>
              <CodeBlock language="typescript">
                {`const res = await fetch("/api/ui/bootstrap", {
  headers: { Authorization: \`Bearer \${process.env.NEXT_PUBLIC_API_KEY}\` },
});`}
              </CodeBlock>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Manage all keys</CardTitle>
              <CardDescription>
                Full key lifecycle (rotate, revoke, scope) is managed via the
                admin endpoints.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <EmptyState
                icon={Key}
                title="Admin UI not yet wired"
                description="For now, manage keys through /v1/api-keys-admin from a service account."
                className="py-6"
              />
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
