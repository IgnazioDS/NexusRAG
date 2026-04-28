"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  FileText,
  Key,
  LayoutDashboard,
  Map as MapIcon,
  Play,
  Search,
  Settings,
  Shield,
  Sparkles,
  Zap,
} from "lucide-react";
import { useCommandPalette } from "./CommandPalette";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { Kbd } from "@/components/ui/kbd";
import { cn, isMac } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: typeof LayoutDashboard;
  desc?: string;
}

const PRIMARY: NavItem[] = [
  { href: "/", label: "Overview", icon: LayoutDashboard, desc: "Dashboard" },
  { href: "/telemetry", label: "Telemetry", icon: Activity, desc: "Live /api/stats" },
  { href: "/documents", label: "Documents", icon: FileText, desc: "Corpus" },
  { href: "/run", label: "Try It", icon: Play, desc: "Live RAG query" },
];

const PROJECT_NAV: NavItem[] = [
  { href: "/capabilities", label: "Capabilities", icon: Sparkles, desc: "What's shipping" },
  { href: "/roadmap", label: "Roadmap", icon: MapIcon, desc: "Stage & direction" },
];

const SECONDARY: NavItem[] = [
  { href: "/api-keys", label: "API Keys", icon: Key },
  { href: "/settings", label: "Settings", icon: Settings },
];

/**
 * Sidebar — primary nav. Fixed-width on desktop. The width is intentionally
 * tight (216px) so dashboards have generous content area. The footer carries
 * a status indicator and the command-palette trigger.
 */
export function Sidebar() {
  const pathname = usePathname();
  const { setOpen: setCommandOpen } = useCommandPalette();
  const metaKey = isMac() ? "⌘" : "Ctrl";

  const renderItem = (item: NavItem) => {
    const active =
      item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
    return (
      <Link
        key={item.href}
        href={item.href}
        className={cn(
          "group relative flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm transition-colors duration-150",
          active
            ? "bg-surface-2 text-foreground"
            : "text-foreground-muted hover:bg-surface-2 hover:text-foreground",
        )}
      >
        {active && (
          <span className="absolute left-0 top-1/2 -translate-y-1/2 h-4 w-0.5 rounded-r bg-brand" />
        )}
        <item.icon
          className={cn(
            "h-3.5 w-3.5 shrink-0",
            active ? "text-brand" : "text-foreground-faint group-hover:text-foreground-muted",
          )}
          strokeWidth={active ? 2 : 1.75}
        />
        <span className="font-medium tracking-tight">{item.label}</span>
        {item.desc && (
          <span className="ml-auto text-2xs text-foreground-faint">
            {item.desc}
          </span>
        )}
      </Link>
    );
  };

  return (
    <aside className="flex h-screen w-[216px] shrink-0 flex-col border-r border-border-subtle bg-surface">
      {/* Brand */}
      <div className="flex h-12 items-center gap-2 border-b border-border-subtle px-3">
        <Link
          href="/"
          className="flex items-center gap-2 group"
          aria-label="NexusRAG home"
        >
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-brand text-brand-foreground">
            <Zap className="h-3.5 w-3.5" strokeWidth={2.5} />
          </div>
          <div className="leading-tight">
            <p className="text-sm font-semibold tracking-tight text-foreground">
              NexusRAG
            </p>
          </div>
        </Link>
        <span className="ml-auto rounded-sm border border-border bg-surface-2 px-1 py-px text-2xs font-medium uppercase tracking-wide text-foreground-faint">
          v2
        </span>
      </div>

      {/* Command palette trigger */}
      <div className="px-2 pt-3">
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              onClick={() => setCommandOpen(true)}
              className={cn(
                "flex w-full items-center gap-2 rounded-md border border-border bg-surface px-2.5 h-7 text-xs",
                "text-foreground-faint hover:text-foreground-muted hover:border-border-strong transition-colors",
              )}
            >
              <Search className="h-3 w-3 shrink-0" />
              <span className="flex-1 text-left">Search…</span>
              <span className="flex items-center gap-1">
                <Kbd>{metaKey}</Kbd>
                <Kbd>K</Kbd>
              </span>
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">Command palette</TooltipContent>
        </Tooltip>
      </div>

      {/* Primary nav */}
      <nav className="flex-1 px-2 pt-3 space-y-0.5 overflow-y-auto">
        <p className="px-2.5 mb-1 text-2xs font-medium uppercase tracking-wider text-foreground-faint">
          Workspace
        </p>
        {PRIMARY.map(renderItem)}

        <p className="mt-4 px-2.5 mb-1 text-2xs font-medium uppercase tracking-wider text-foreground-faint">
          Project
        </p>
        {PROJECT_NAV.map(renderItem)}

        <p className="mt-4 px-2.5 mb-1 text-2xs font-medium uppercase tracking-wider text-foreground-faint">
          Account
        </p>
        {SECONDARY.map(renderItem)}
      </nav>

      {/* Footer status */}
      <div className="border-t border-border-subtle p-3">
        <div className="flex items-center gap-2 rounded-md border border-success/20 bg-success/5 px-2.5 py-1.5">
          <Shield className="h-3 w-3 text-success shrink-0" />
          <div className="leading-none">
            <p className="text-2xs font-medium text-success">SOC 2 Ready</p>
            <p className="mt-0.5 text-2xs text-foreground-faint">
              Audit logging on
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
}
