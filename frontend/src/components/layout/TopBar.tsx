"use client";
import { useEffect, useState } from "react";
import { RefreshCw, Wifi } from "lucide-react";
import { fetchBootstrap, type BootstrapData } from "@/lib/api";
import { cn } from "@/lib/utils";

export function TopBar({ title }: { title: string }) {
  const [bootstrap, setBootstrap] = useState<BootstrapData | null>(null);
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    fetchBootstrap()
      .then((d) => { setBootstrap(d); setConnected(true); })
      .catch(() => setConnected(false));
  }, []);

  const tenant = bootstrap?.principal.tenant_id ?? "—";
  const role = bootstrap?.principal.role ?? "—";

  return (
    <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-white/[0.06] bg-[#080810]/80 px-5 backdrop-blur-xl">
      <div className="flex items-center gap-2">
        <h1 className="text-[13px] font-semibold text-zinc-100 tracking-tight">{title}</h1>
      </div>

      <div className="flex items-center gap-3">
        {/* API status */}
        <div className="flex items-center gap-2 rounded-full border border-white/[0.06] bg-white/[0.03] px-2.5 py-1">
          <span
            className={cn(
              "relative h-1.5 w-1.5 rounded-full",
              connected === true
                ? "bg-emerald-400 pulse-dot text-emerald-400"
                : connected === false
                ? "bg-red-400"
                : "bg-zinc-600"
            )}
          />
          <span className="text-[11px] font-medium text-zinc-500 hidden sm:inline">
            {connected === true ? "API connected" : connected === false ? "Disconnected" : "Connecting…"}
          </span>
        </div>

        <div className="h-3.5 w-px bg-white/[0.08]" />

        {/* Tenant + role */}
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-zinc-500">{tenant}</span>
          <span className="rounded-md border border-indigo-500/20 bg-indigo-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-indigo-400">
            {role}
          </span>
        </div>

        <div className="h-3.5 w-px bg-white/[0.08]" />

        <button
          onClick={() => window.location.reload()}
          className="rounded-md p-1.5 text-zinc-600 transition-all hover:bg-white/[0.05] hover:text-zinc-300"
          title="Refresh"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>
    </header>
  );
}
