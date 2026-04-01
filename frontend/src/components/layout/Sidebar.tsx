"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, FileText, Play, Zap, Shield, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard, desc: "Platform metrics" },
  { href: "/documents", label: "Documents", icon: FileText, desc: "Corpus management" },
  { href: "/run", label: "Try It", icon: Play, desc: "Live RAG query" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex h-screen w-[220px] shrink-0 flex-col border-r border-white/[0.06] bg-[#080810]">
      {/* Logo */}
      <div className="flex h-[52px] items-center gap-2.5 border-b border-white/[0.06] px-4">
        <div className="relative flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 shadow-lg shadow-indigo-500/30">
          <Zap className="h-4 w-4 text-white" strokeWidth={2.5} />
          <div className="absolute inset-0 rounded-lg bg-indigo-400/20 blur-sm" />
        </div>
        <div>
          <p className="text-[13px] font-semibold tracking-tight text-white">NexusRAG</p>
          <p className="text-[10px] text-zinc-600 leading-none">Platform v2</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-0.5 p-2 pt-3">
        <p className="mb-1.5 px-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-zinc-700">
          Navigation
        </p>
        {NAV.map(({ href, label, icon: Icon, desc }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-all duration-150",
                active ? "nav-active text-indigo-300" : "text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-200"
              )}
            >
              <div className={cn(
                "flex h-6 w-6 shrink-0 items-center justify-center rounded-md transition-colors",
                active ? "bg-indigo-500/20 text-indigo-400" : "text-zinc-600 group-hover:text-zinc-300"
              )}>
                <Icon className="h-3.5 w-3.5" strokeWidth={active ? 2.5 : 2} />
              </div>
              <div className="min-w-0 flex-1">
                <p className={cn("text-[13px] font-medium leading-none", active ? "text-zinc-100" : "")}>{label}</p>
                <p className="mt-0.5 text-[10px] leading-none text-zinc-700">{desc}</p>
              </div>
              {active && <ChevronRight className="h-3 w-3 text-indigo-500/60 shrink-0" />}
            </Link>
          );
        })}
      </nav>

      {/* Bottom */}
      <div className="border-t border-white/[0.06] p-3 space-y-2">
        <div className="flex items-center gap-2.5 rounded-lg bg-emerald-500/5 border border-emerald-500/10 px-3 py-2">
          <div className="relative shrink-0">
            <Shield className="h-3.5 w-3.5 text-emerald-400" />
          </div>
          <div>
            <p className="text-[11px] font-medium text-emerald-400 leading-none">SOC 2 Ready</p>
            <p className="mt-0.5 text-[10px] text-zinc-700 leading-none">Audit logging active</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
