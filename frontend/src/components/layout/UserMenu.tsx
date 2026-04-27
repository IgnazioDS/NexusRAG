"use client";

import {
  ChevronDown,
  ExternalLink,
  Github,
  LifeBuoy,
  LogOut,
  Settings,
  User,
} from "lucide-react";
import {
  Avatar,
  AvatarFallback,
} from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";

interface UserMenuProps {
  tenantId: string;
  role: string;
}

/**
 * UserMenu — avatar + tenant + role + dropdown. Plays the role of the
 * top-right avatar on every Vercel-style dashboard.
 */
export function UserMenu({ tenantId, role }: UserMenuProps) {
  const initials = (tenantId || "??").slice(0, 2).toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex items-center gap-2 rounded-md p-1 hover:bg-surface-2 transition-colors group">
          <Avatar className="h-6 w-6">
            <AvatarFallback className="bg-brand/15 text-brand text-2xs">
              {initials}
            </AvatarFallback>
          </Avatar>
          <span className="font-mono text-2xs text-foreground-muted hidden sm:inline">
            {tenantId}
          </span>
          <ChevronDown className="h-3 w-3 text-foreground-faint group-hover:text-foreground-muted transition-colors" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="flex items-center justify-between normal-case tracking-normal">
          <div className="flex flex-col gap-0.5">
            <span className="text-2xs uppercase tracking-wider text-foreground-faint">
              Tenant
            </span>
            <span className="font-mono text-xs text-foreground">{tenantId}</span>
          </div>
          <Badge variant="brand">{role}</Badge>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem>
          <User className="h-3.5 w-3.5" /> Profile
        </DropdownMenuItem>
        <DropdownMenuItem>
          <Settings className="h-3.5 w-3.5" /> Settings
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <a
            href="https://github.com/IgnazioDS/NexusRAG"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2"
          >
            <Github className="h-3.5 w-3.5" /> GitHub
            <ExternalLink className="ml-auto h-3 w-3" />
          </a>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <LifeBuoy className="h-3.5 w-3.5" /> Support
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="text-danger focus:text-danger">
          <LogOut className="h-3.5 w-3.5" /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
