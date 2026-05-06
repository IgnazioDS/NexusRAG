"use client";

import { useEffect, useState } from "react";
import { Github, Globe, Sparkles } from "lucide-react";
import { useTheme } from "next-themes";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const [bootstrap, setBootstrap] = useState<BootstrapData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchBootstrap()
      .then((d) => setBootstrap(d))
      .catch(() => null)
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <TopBar
        title="Settings"
        description="Workspace, theme, and connection preferences"
      />
      <div className="flex-1 overflow-y-auto">
        <div className="page-enter mx-auto max-w-3xl space-y-5 p-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-3.5 w-3.5 text-brand" />
                Appearance
              </CardTitle>
              <CardDescription>
                Switches between dark, light, and system-default themes.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between">
                <p className="text-sm text-foreground-muted">Theme</p>
                <Select value={theme ?? "dark"} onValueChange={setTheme}>
                  <SelectTrigger className="w-40">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="dark">Dark</SelectItem>
                    <SelectItem value="light">Light</SelectItem>
                    <SelectItem value="system">System</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Globe className="h-3.5 w-3.5 text-brand" />
                Workspace
              </CardTitle>
              <CardDescription>
                Tenant identity, plan, and feature flags.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {loading ? (
                <>
                  <Skeleton className="h-4 w-48" />
                  <Skeleton className="h-4 w-32" />
                </>
              ) : bootstrap ? (
                <>
                  <KV label="Tenant ID" value={bootstrap.principal.tenant_id} mono />
                  <KV label="Role" value={bootstrap.principal.role} />
                  <KV
                    label="Plan"
                    value={bootstrap.plan.plan_name ?? bootstrap.plan.plan_id}
                  />
                  <div>
                    <p className="text-2xs uppercase tracking-wider text-foreground-faint mb-2">
                      Entitlements
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(bootstrap.entitlements).map(
                        ([key, val]) => (
                          <Badge
                            key={key}
                            variant={val.enabled ? "success" : "muted"}
                          >
                            {key}
                          </Badge>
                        ),
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <p className="text-sm text-foreground-subtle">
                  Workspace info unavailable. Ensure your API key is configured.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Resources</CardTitle>
              <CardDescription>
                External links for documentation and source.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Button asChild variant="outline" size="default">
                <a
                  href="https://github.com/IgnazioDS/NexusRAG"
                  target="_blank"
                  rel="noreferrer"
                >
                  <Github />
                  GitHub
                </a>
              </Button>
              <Button asChild variant="outline" size="default">
                <a href="/v1/docs" target="_blank" rel="noreferrer">
                  API Docs (Swagger)
                </a>
              </Button>
              <Button asChild variant="outline" size="default">
                <a
                  href="https://github.com/IgnazioDS/IgnazioDS/blob/main/TELEMETRY_SCHEMA.md"
                  target="_blank"
                  rel="noreferrer"
                >
                  Telemetry Schema
                </a>
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}

function KV({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <p className="text-2xs font-medium uppercase tracking-wider text-foreground-faint">
        {label}
      </p>
      <p
        className={`text-sm font-medium text-foreground ${
          mono ? "font-mono" : ""
        }`}
      >
        {value}
      </p>
    </div>
  );
}
