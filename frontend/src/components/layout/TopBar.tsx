"use client";

import { useEffect, useState } from "react";
import { fetchBootstrap, type BootstrapData } from "@/lib/api";
import { StatusDot } from "@/components/ui/status-dot";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { ThemeToggle } from "./ThemeToggle";
import { UserMenu } from "./UserMenu";
import { Breadcrumbs } from "./Breadcrumbs";

interface TopBarProps {
  /** Page title shown when there's no breadcrumb context (i.e. on the root). */
  title: string;
  description?: string;
  actions?: React.ReactNode;
}

/**
 * TopBar — sticky page header. Carries breadcrumbs (or page title on root),
 * API status indicator, theme toggle, and user menu. Frosted via backdrop
 * blur so it floats over the dot-grid backgrounds.
 */
export function TopBar({ title, description, actions }: TopBarProps) {
  const [bootstrap, setBootstrap] = useState<BootstrapData | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    fetchBootstrap()
      .then((d) => {
        setBootstrap(d);
        setConnected(true);
      })
      .catch(() => setConnected(false));
  }, []);

  const tenant = bootstrap?.principal.tenant_id ?? "—";
  const role = bootstrap?.principal.role ?? "viewer";

  return (
    <header className="sticky top-0 z-30 flex h-12 shrink-0 items-center justify-between gap-3 border-b border-border-subtle bg-background/85 px-5 backdrop-blur">
      <div className="flex min-w-0 items-center gap-3">
        <Breadcrumbs />
        <div className="min-w-0">
          <h1 className="text-sm font-semibold tracking-tight text-foreground truncate">
            {title}
          </h1>
          {description && (
            <p className="text-2xs text-foreground-subtle truncate">
              {description}
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2">
        {actions}

        {/* API status pill */}
        <Tooltip>
          <TooltipTrigger asChild>
            <div className="flex items-center gap-2 rounded-md border border-border bg-surface px-2 py-1">
              <StatusDot
                tone={
                  connected === true
                    ? "success"
                    : connected === false
                    ? "danger"
                    : "muted"
                }
                pulse={connected === true}
                size="sm"
              />
              <span className="text-2xs font-medium text-foreground-muted hidden md:inline">
                {connected === true
                  ? "Connected"
                  : connected === false
                  ? "Offline"
                  : "Connecting"}
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent>
            {connected === true
              ? "API reachable"
              : connected === false
              ? "Could not reach the API"
              : "Establishing connection…"}
          </TooltipContent>
        </Tooltip>

        <div className="h-4 w-px bg-border" aria-hidden />

        <ThemeToggle />

        <div className="h-4 w-px bg-border" aria-hidden />

        <UserMenu tenantId={tenant} role={role} />
      </div>
    </header>
  );
}
